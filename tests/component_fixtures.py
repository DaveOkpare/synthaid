"""Import-safe components used through their documented public contracts."""

from collections.abc import Mapping

from agentinstruct import (
    Agents,
    FunctionCall,
    Message,
    Observation,
    ReviewRequest,
    ReviewResult,
    TaskContext,
    ToolCall,
    ToolContext,
    TraceSnapshot,
    VerificationResult,
)
from agentinstruct.plans import (
    AgentPlan,
    FrozenJsonValue,
    JsonValue,
    ReviewerPlan,
    ToolPlan,
    VerifierPlan,
)
from agentinstruct.traces import GenerationOutcome


class RoundTable:
    def __init__(self) -> None:
        self.used = False

    async def setup(self, agents: Agents) -> None:
        if self.used:
            raise ValueError("Environment was reused across Traces")
        self.used = True
        if len(agents) != 3:
            raise ValueError("Expected three participants")

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        incoming = None
        for actor in agents:
            async with agents[actor].interaction(task) as interaction:
                incoming = (await interaction.turn(incoming)).last_reply
        return GenerationOutcome("terminated", "round_table_complete")


class Participant:
    def __init__(self, plan: AgentPlan) -> None:
        self.plan = plan
        self.calls = 0

    async def generate(self, observation: Observation) -> Message:
        self.calls += 1
        if self.plan.target:
            if not observation.messages or observation.messages[-1].role != "tool":
                return Message(
                    "assistant",
                    tool_calls=(
                        ToolCall(
                            "lookup",
                            FunctionCall(
                                "lookup",
                                {
                                    "label": "safe"
                                    if observation.review_feedback
                                    else "reject",
                                },
                            ),
                        ),
                    ),
                )
            return Message(
                "assistant", "Target result: " + observation.messages[-1].content
            )
        return Message(
            "assistant", f"{self.plan.id}:{self.calls}:seen={len(observation.messages)}"
        )


class Lookup:
    def __init__(self, plan: ToolPlan) -> None:
        self.id = plan.id
        self.description = plan.description
        self.input_schema = plan.input_schema
        self.output_schema = plan.output_schema
        self.execution_errors = plan.execution_errors

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        return {"label": str(args["label"]), "actor": context.actor_id}


class Reviewer:
    def __init__(self, plan: ReviewerPlan) -> None:
        self.plan = plan

    async def review(self, request: ReviewRequest) -> ReviewResult:
        approved = (
            not request.message.tool_calls
            or request.message.tool_calls[0].function.arguments["label"] == "safe"
        )
        return ReviewResult(
            {criterion.id: approved for criterion in request.rubric.criteria},
            "Use safe label",
        )


class Verifier:
    def __init__(self, plan: VerifierPlan) -> None:
        self.plan = plan

    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        valid = trace.generation.state == "terminated" and len(trace.conversation) == 5
        return VerificationResult(
            {criterion.id: valid for criterion in self.plan.rubric.criteria}
        )


class MissingAgent:
    def __init__(self, plan: AgentPlan) -> None:
        raise AssertionError("Validation must not construct components")


class WrongSignatureAgent:
    def __init__(self, plan: AgentPlan) -> None:
        pass

    async def generate(self) -> Message:
        return Message("assistant", "bad")


class ConstructorGuard(Participant):
    def __init__(self, plan: AgentPlan) -> None:
        raise RuntimeError("Construct only when running")


class WrongEnvironment:
    def __init__(self, plan: AgentPlan) -> None:
        pass

    async def setup(self, agents: Agents) -> None:
        pass

    async def run(self, task: TaskContext, agents: Agents) -> None:
        pass


class WrongReviewer:
    def __init__(self, plan: ReviewerPlan) -> None:
        pass

    def review(self, request: ReviewRequest) -> ReviewResult:
        return ReviewResult({})


class MissingTool:
    def __init__(self, plan: ToolPlan) -> None:
        pass

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        return None


async def lookup_function(
    args: Mapping[str, FrozenJsonValue], context: ToolContext
) -> JsonValue:
    return {"label": str(args["label"]), "actor": context.actor_id}


class Subordinate:
    def __init__(self, config: Mapping[str, FrozenJsonValue]) -> None:
        self.config = config
        self.calls = 0

    async def generate(self, observation: Observation) -> Message:
        import json

        self.calls += 1
        return Message(
            "assistant",
            json.dumps(
                {
                    "label": str(self.config["label"]),
                    "instruction": observation.instruction,
                    "calls": self.calls,
                }
            ),
        )


class ClassMethodParticipant(Participant):
    @classmethod
    async def generate(cls, observation: Observation) -> Message:
        return Message("assistant", f"{cls.__name__}:{observation.actor_id}")


class StaticMethodLookup(Lookup):
    @staticmethod
    async def call(
        args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        return await lookup_function(args, context)


class StaticMethodFinalizingRoundTable(RoundTable):
    @staticmethod
    async def finalize(task: TaskContext, trace: TraceSnapshot) -> None:
        if trace.generation.state != "terminated":
            raise ValueError("Only completed round tables should be finalized")


class ClassMethodFinalizingRoundTable(RoundTable):
    @classmethod
    async def finalize(cls, task: TaskContext, trace: TraceSnapshot) -> None:
        await StaticMethodFinalizingRoundTable.finalize(task, trace)
