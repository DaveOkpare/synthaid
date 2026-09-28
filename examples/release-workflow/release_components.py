"""Deterministic release fixture; no credentials, clients or storage at import."""

import json
from collections.abc import Mapping

from agentinstruct import (
    FunctionCall,
    Message,
    Observation,
    ReviewRequest,
    ReviewResult,
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


def call(identifier: str, name: str, args: Mapping[str, FrozenJsonValue]) -> Message:
    return Message(
        "assistant", tool_calls=(ToolCall(identifier, FunctionCall(name, args)),)
    )


class Participant:
    def __init__(self, plan: AgentPlan) -> None:
        self.target = plan.target
        self.name, self.outcome = plan.base_instruction.strip().splitlines()
        self.calls = 0

    async def generate(self, observation: Observation) -> Message:
        self.calls += 1
        if not self.target:
            if self.calls == 1:
                return Message("assistant", "DRAFT " + self.name)
            # A peer must never receive the target's private Tool exchange.
            if any(
                message.tool_calls or message.role == "tool"
                for message in observation.messages
            ):
                raise ValueError("Private Tool activity reached the simulator")
            return Message(
                "assistant",
                f"User {self.name}; turn={self.calls - 1}; step={observation.step_id}",
            )
        if self.calls == 1:
            return call("rejected-call", "lookup", {"label": "reject"})
        if self.calls == 2:
            return call("lookup", "lookup", {"label": "safe"})
        if self.calls == 3:
            result = json.loads(observation.messages[-1].content)
            return Message(
                "assistant", f"Collected {self.name}; invocation={result['invocation']}"
            )
        if self.calls == 4:
            if self.outcome == "failed":
                raise ValueError("Deliberate post-commit generation failure")
            return call("advance", "advance_step", {"step_id": "conclude"})
        if self.calls == 5:
            retained = any(
                message.content == f"Collected {self.name}; invocation=1"
                for message in observation.messages
            )
            return Message("assistant", f"Conclude {self.name}; retained={retained}")
        if self.calls == 6:
            return call("complete", "complete_task", {})
        return Message("assistant", f"Final {self.name}")


class Lookup:
    def __init__(self, plan: ToolPlan) -> None:
        self.id, self.description = plan.id, plan.description
        self.input_schema, self.output_schema = plan.input_schema, plan.output_schema
        self.execution_errors = plan.execution_errors
        self.calls = 0

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        if args["label"] != "safe":
            raise ValueError("Rejected Tool call executed")
        self.calls += 1
        return {
            "label": args["label"],
            "invocation": self.calls,
            "seed": context.seed_id,
        }


class Reviewer:
    def __init__(self, plan: ReviewerPlan) -> None:
        pass

    async def review(self, request: ReviewRequest) -> ReviewResult:
        safe = not request.message.content.startswith("DRAFT") and all(
            call.function.arguments.get("label") != "reject"
            for call in request.message.tool_calls
        )
        return ReviewResult(
            {criterion.id: safe for criterion in request.rubric.criteria},
            "Use accepted wording and a safe label.",
        )


class Verifier:
    def __init__(self, plan: VerifierPlan) -> None:
        pass

    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        seed = trace.run_plan["seed"]
        assert isinstance(seed, Mapping) and isinstance(seed["data"], Mapping)
        outcome = seed["data"]["outcome"]
        if outcome == "unverified":
            raise ValueError("Deliberate Verifier failure")
        complete = trace.generation.state == "terminated" and outcome == "accepted"
        complete = complete and any(
            item.message.content == f"Conclude {seed['data']['name']}; retained=True"
            for item in trace.conversation
        )
        return VerificationResult({"complete": complete})
