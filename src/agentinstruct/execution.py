"""Agent protocols and the Interaction acceptance boundary."""

from collections import deque
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Literal, Protocol, cast
from uuid import uuid4

from agentinstruct.plans import (
    AgentPlan,
    EnvironmentPlan,
    FrozenJsonValue,
    TaskIdentity,
    ToolPlan,
    canonical_json,
)
from agentinstruct.quality import Rubric, score_verdicts
from agentinstruct.review import (
    Reviewer,
    ReviewError,
    ReviewExhausted,
    ReviewRequest,
    ReviewResult,
)
from agentinstruct.steps import CONTROL_TOOLS, StepProgress
from agentinstruct.store import TraceRecorder, timestamp
from agentinstruct.tools import (
    Tool,
    ToolContext,
    ToolError,
    ToolExecutionFailure,
    tool_result_content,
    validate_tool_data,
)
from agentinstruct.traces import (
    Event,
    FunctionCall,
    GenerationOutcome,
    Message,
    MessageCommit,
    ToolCall,
    TraceSnapshot,
    immutable_data,
)


@dataclass(frozen=True)
class Observation:
    actor_id: str
    instruction: str
    messages: tuple[Message, ...]
    review_feedback: str | None = None
    tools: tuple[ToolPlan, ...] = ()
    step_id: str | None = None
    turn_id: str | None = None


class Agent(Protocol):
    async def generate(self, observation: Observation) -> Message | list[Message]: ...


class ScriptedAgent:
    """Deterministic literal responses, consumed once per generation proposal."""

    def __init__(self, plan: AgentPlan) -> None:
        self._responses = iter(plan.responses)

    async def generate(self, observation: Observation) -> Message:
        try:
            response = next(self._responses)
        except StopIteration as exc:
            raise ValueError("Scripted Agent has no remaining responses") from exc
        if isinstance(response, str):
            return Message(role="assistant", content=response)
        return Message(
            role="assistant", content=response.content, control=response.control
        )


def create_agent(plan: AgentPlan) -> Agent:
    from agentinstruct.components import construct_component

    return cast(Agent, construct_component("agent", plan.type, plan))


@dataclass(frozen=True)
class TaskContext:
    task: TaskIdentity
    seed_id: str
    variables: Mapping[str, FrozenJsonValue]
    max_turns: int
    max_rounds: int = 10
    timeout_seconds: float | None = None
    steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "variables", immutable_data(self.variables))
        object.__setattr__(self, "steps", tuple(self.steps))

    def advance_step(self, step_id: str) -> Message:
        """Propose a transition; submit through the Target Interaction's control()."""
        return Message(
            "assistant",
            tool_calls=(
                ToolCall(
                    uuid4().hex, FunctionCall("advance_step", {"step_id": step_id})
                ),
            ),
        )

    def complete_task(self) -> Message:
        """Propose completion through the same reviewed boundary as Agent Tools."""
        return Message(
            "assistant",
            tool_calls=(ToolCall(uuid4().hex, FunctionCall("complete_task", {})),),
        )


@dataclass(frozen=True)
class TurnResult:
    last_reply: Message
    terminated: bool = False


class Interaction:
    def __init__(
        self,
        plan: AgentPlan,
        agent: Agent,
        recorder: TraceRecorder,
        reviewer: Reviewer | None = None,
        tools: Mapping[str, Tool] | None = None,
        tool_plans: Mapping[str, ToolPlan] | None = None,
        tool_context: ToolContext | None = None,
        progress: StepProgress | None = None,
    ) -> None:
        self._plan = plan
        self._agent = agent
        self._recorder = recorder
        self._reviewer = reviewer
        self._tools = tools or {}
        self._tool_plans = tool_plans or {}
        self._tool_context = tool_context
        self._progress = progress or StepProgress((), recorder)

    @property
    def _instruction(self) -> str:
        active = self._progress.active
        return self._plan.base_instruction + (
            "\n\n" + active.agents[self._plan.id].instruction if active else ""
        )

    def _observation(
        self, feedback: str | None = None, *, turn_id: str | None = None
    ) -> Observation:
        return Observation(
            self._plan.id,
            self._instruction,
            tuple(
                item.message
                for item in self._recorder.conversation
                if item.visibility == "shared" or item.message.actor_id == self._plan.id
            ),
            feedback,
            ()
            if self._progress.completed
            else (
                tuple(self._tool_plans[tool_id] for tool_id in self._plan.tools)
                + (self._progress.available_controls if self._plan.target else ())
            ),
            self._progress.step_id,
            turn_id,
        )

    def _event(
        self, kind: str, data: object, turn_id: str, step_id: str | None = None
    ) -> None:
        self._recorder.event(
            Event(
                uuid4().hex,
                kind,
                timestamp(),
                immutable_data(data),
                self._plan.id,
                turn_id,
                step_id if step_id is not None else self._progress.step_id,
            )
        )

    def _proposal(self, proposal: Message, turn_id: str) -> Message:
        if (
            not isinstance(proposal, Message)
            or proposal.role not in {"assistant", "user"}
            or not isinstance(proposal.content, str)
        ):
            raise ValueError("Agent must return participant Messages")
        if proposal.tool_call_id is not None or (
            proposal.tool_calls
            and (proposal.role != "assistant" or proposal.control is not None)
        ):
            raise ValueError("Invalid Tool-call Message shape")
        for call in proposal.tool_calls:
            if (
                not isinstance(call, ToolCall)
                or call.type != "function"
                or not isinstance(call.id, str)
                or not call.id.strip()
                or not isinstance(call.function, FunctionCall)
                or not isinstance(call.function.name, str)
                or not call.function.name.strip()
            ):
                raise ValueError(
                    "Tool calls require function names and stable identifiers"
                )
        call_ids = [call.id for call in proposal.tool_calls]
        accepted_ids = {
            call.id
            for commit in self._recorder.conversation
            if commit.message.actor_id == self._plan.id
            for call in commit.message.tool_calls
        }
        if len(set(call_ids)) != len(call_ids) or accepted_ids.intersection(call_ids):
            raise ValueError("Tool call identifiers must be unique for each Agent")
        if proposal.control not in {None, "complete"}:
            raise ValueError("Unknown Message control proposal")
        if proposal.control is not None and self._progress.steps:
            raise ValueError(
                "Task Steps require complete_task Tool calls instead of Message.control"
            )
        if (
            any(call.function.name in CONTROL_TOOLS for call in proposal.tool_calls)
            and len(proposal.tool_calls) != 1
        ):
            raise ValueError("Task Step control must be the only call in its Message")
        if proposal.control == "complete" and not self._plan.target:
            raise ValueError("Only the Target Agent may complete the Task")
        message = replace(proposal, id=uuid4().hex, actor_id=self._plan.id)
        self._event("proposal", message, turn_id)
        return message

    async def _review(
        self, message: Message, turn_id: str
    ) -> tuple[str | None, str | None]:
        if self._plan.reviewer is None:
            return None, None
        assert self._reviewer is not None and self._plan.rubric is not None
        active = self._progress.active
        rubric = Rubric(
            self._plan.rubric.criteria
            + (active.agents[self._plan.id].appended_rubric if active else ()),
            self._plan.rubric.threshold,
        )
        review_id = uuid4().hex
        request = ReviewRequest(
            self._plan.reviewer.instruction,
            rubric,
            message,
            self._observation().messages,
            self._instruction,
            self._progress.step_id,
            self._plan.id,
            turn_id,
        )
        self._event(
            "review_requested",
            {"review_id": review_id, "message_id": message.id, "request": request},
            turn_id,
        )
        stage: Literal["execution", "malformed"] = "execution"
        try:
            result = await self._reviewer.review(request)
            stage = "malformed"
            if not isinstance(result, ReviewResult) or not isinstance(
                result.feedback, str
            ):
                raise ValueError(
                    "Reviewer must return a ReviewResult with text feedback"
                )
            score = score_verdicts(request.rubric, result.criteria)
        except Exception as exc:
            self._event(
                "review_error",
                {
                    "review_id": review_id,
                    "message_id": message.id,
                    "kind": stage,
                    "exception": type(exc).__name__,
                    "message": str(exc),
                },
                turn_id,
            )
            raise ReviewError(stage) from exc
        accepted = score >= request.rubric.threshold
        self._event(
            "review_result",
            {
                "review_id": review_id,
                "message_id": message.id,
                "criteria": dict(result.criteria),
                "feedback": result.feedback,
                "score": score,
                "accepted": accepted,
            },
            turn_id,
        )
        if not accepted:
            self._event(
                "rejection",
                {"review_id": review_id, "message": message},
                turn_id,
            )
        return review_id, None if accepted else result.feedback

    async def turn(self, incoming: Message | None = None) -> TurnResult:
        return await self._turn(incoming)

    async def control(self, proposal: Message) -> TurnResult:
        """Submit an Environment control proposal to the Target's normal review loop."""
        if (
            len(proposal.tool_calls) != 1
            or proposal.tool_calls[0].function.name not in CONTROL_TOOLS
        ):
            raise ValueError("Environment controls require one Task Step control call")
        return await self._turn(action=proposal)

    async def _turn(
        self,
        incoming: Message | None = None,
        *,
        action: Message | list[Message] | None = None,
    ) -> TurnResult:
        self._recorder.require_open()
        if self._progress.completed:
            raise ValueError("Task is already complete")
        if incoming is not None and not any(
            item.message == incoming for item in self._recorder.conversation
        ):
            raise ValueError("Incoming reply must reference an accepted Message")
        turn_id = uuid4().hex
        if action is None:
            action = await self._agent.generate(self._observation(turn_id=turn_id))
        proposals = deque(action if isinstance(action, list) else [action])
        if not proposals:
            raise ValueError("Agent returned no Messages")
        last_reply: Message | None = None
        while proposals:
            message = self._proposal(proposals.popleft(), turn_id)
            revisions = 0
            review_exhausted = False
            while True:
                if message.tool_calls and proposals:
                    raise ValueError(
                        "Tool-call Message must be the last pending Message; "
                        "the Agent must observe its result before continuing"
                    )
                review_id, feedback = await self._review(message, turn_id)
                if feedback is None:
                    break
                assert self._plan.reviewer is not None
                if revisions >= self._plan.reviewer.max_revisions:
                    review_exhausted = (
                        self._plan.reviewer.accept_on_revision_exhaustion
                        and message.control is None
                        and not message.tool_calls
                    )
                    self._event(
                        "review_exhausted",
                        {
                            "review_id": review_id,
                            "message_id": message.id,
                            "accepted": review_exhausted,
                        },
                        turn_id,
                    )
                    if review_exhausted:
                        break
                    raise ReviewExhausted("Reviewer revisions exhausted")
                revision = await self._agent.generate(
                    self._observation(feedback, turn_id=turn_id)
                )
                revised = revision if isinstance(revision, list) else [revision]
                if not revised:
                    raise ValueError("Agent returned no Messages")
                # The first replacement consumes this Message's revision budget;
                # its additional Messages are independent subsequent subjects.
                proposals.extendleft(reversed(revised[1:]))
                previous_id = message.id
                message = self._proposal(revised[0], turn_id)
                revisions += 1
                self._event(
                    "revision",
                    {
                        "message_id": message.id,
                        "revises_message_id": previous_id,
                        "review_id": review_id,
                        "revision": revisions,
                    },
                    turn_id,
                )
            self._recorder.commit(
                MessageCommit(
                    message,
                    turn_id,
                    timestamp(),
                    step_id=self._progress.step_id,
                    causal_message_id=incoming.id if incoming else None,
                    review_id=review_id,
                    review_exhausted=review_exhausted,
                    visibility="private" if message.tool_calls else "shared",
                )
            )
            self._event("message_committed", {"message_id": message.id}, turn_id)
            if message.tool_calls:
                for call in message.tool_calls:
                    await self._execute_tool(call, message, turn_id)
                continuation = await self._agent.generate(
                    self._observation(turn_id=turn_id)
                )
                proposals.extend(
                    continuation if isinstance(continuation, list) else [continuation]
                )
                if not proposals:
                    raise ValueError("Agent returned no Messages")
                continue
            last_reply = message
            if message.control == "complete":
                return TurnResult(message, terminated=True)
        assert last_reply is not None
        return TurnResult(last_reply, terminated=self._progress.completed)

    async def _execute_tool(
        self, call: ToolCall, message: Message, turn_id: str
    ) -> None:
        stage: Literal["assignment", "arguments", "execution", "result"] = "assignment"
        step_id = self._progress.step_id
        try:
            control = call.function.name in CONTROL_TOOLS
            if (
                self._progress.completed
                or (control and not (self._plan.target and self._progress.steps))
                or (not control and call.function.name not in self._plan.tools)
            ):
                raise ValueError("Tool is not assigned to the invoking Agent")
            tool_plan = (
                CONTROL_TOOLS[call.function.name]
                if control
                else self._tool_plans[call.function.name]
            )
            stage = "arguments"
            validate_tool_data(call.function.arguments, tool_plan.input_schema)
            assert self._tool_context is not None
            self._event(
                "tool_started",
                {"message_id": message.id, "tool_call_id": call.id},
                turn_id,
            )
            stage = "execution"
            if control:
                result = self._progress.apply(
                    call.function.name,
                    call.function.arguments,
                    actor_id=self._plan.id,
                    turn_id=turn_id,
                    message_id=message.id,
                )
            else:
                result = await self._tools[call.function.name].call(
                    call.function.arguments,
                    replace(
                        self._tool_context,
                        turn_id=turn_id,
                        tool_call_id=call.id,
                        step_id=step_id,
                    ),
                )
            stage = "result"
            content = tool_result_content(result, tool_plan.output_schema)
        except Exception as exc:
            kind = exc.kind if isinstance(exc, ToolError) else stage
            self._event(
                "tool_error",
                {
                    "message_id": message.id,
                    "tool_call_id": call.id,
                    "kind": kind,
                    "exception": type(exc).__name__,
                    "message": "Tool execution failed"
                    if stage == "execution"
                    else str(exc),
                },
                turn_id,
                step_id,
            )
            if (
                stage == "execution"
                and kind == "execution"
                and tool_plan.execution_errors == "result"
            ):
                content = canonical_json(
                    {"error": ToolExecutionFailure(type(exc).__name__)}
                )
            else:
                raise ToolError(kind) from exc
        response = Message(
            "tool",
            content,
            id=uuid4().hex,
            actor_id=self._plan.id,
            tool_call_id=call.id,
        )
        self._recorder.commit(
            MessageCommit(
                response,
                turn_id,
                timestamp(),
                step_id=step_id,
                visibility="private",
                causal_message_id=message.id,
            )
        )
        self._event("message_committed", {"message_id": response.id}, turn_id, step_id)


class AgentHandle:
    """Trace-bound facade: Environments interact without recorder access."""

    def __init__(
        self,
        plan: AgentPlan,
        agent: Agent,
        recorder: TraceRecorder,
        reviewer: Reviewer | None = None,
        tools: Mapping[str, Tool] | None = None,
        tool_plans: Mapping[str, ToolPlan] | None = None,
        tool_context: ToolContext | None = None,
        progress: StepProgress | None = None,
    ) -> None:
        self._interaction = Interaction(
            plan, agent, recorder, reviewer, tools, tool_plans, tool_context, progress
        )

    @asynccontextmanager
    async def interaction(self, task: TaskContext) -> AsyncIterator[Interaction]:
        yield self._interaction


class Agents(Mapping[str, AgentHandle]):
    def __init__(self, agents: Mapping[str, AgentHandle]) -> None:
        self._agents = dict(agents)

    def __getitem__(self, key: str) -> AgentHandle:
        return self._agents[key]

    def __len__(self) -> int:
        return len(self._agents)

    def __iter__(self) -> Iterator[str]:
        return iter(self._agents)


class Environment(Protocol):
    async def setup(self, agents: Agents) -> None: ...

    async def run(
        self, task: TaskContext, agents: Agents
    ) -> GenerationOutcome | None: ...


class FinalizingEnvironment(Protocol):
    async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None: ...


class SingleAgentEnvironment:
    async def setup(self, agents: Agents) -> None:
        if len(agents) != 1:
            raise ValueError("single Environment requires exactly one Agent")

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        async with agents[next(iter(agents))].interaction(task) as interaction:
            for _ in range(task.max_turns):
                result = await interaction.turn()
                if result.terminated or not task.steps:
                    return GenerationOutcome("terminated", "completed")
        return GenerationOutcome("truncated", "max_turns")


class DialogueEnvironment:
    def __init__(self, initiator: str = "user") -> None:
        if initiator not in {"user", "assistant"}:
            raise ValueError("dialogue initiator must be user or assistant")
        self._initiator = initiator

    async def setup(self, agents: Agents) -> None:
        if set(agents) != {"user", "assistant"}:
            raise ValueError("dialogue Environment requires user and assistant Agents")

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        async with (
            agents["user"].interaction(task) as user,
            agents["assistant"].interaction(task) as assistant,
        ):
            interactions = {"user": user, "assistant": assistant}
            actor = self._initiator
            incoming = None
            for _ in range(task.max_rounds * 2):
                result = await interactions[actor].turn(incoming)
                if result.terminated:
                    return GenerationOutcome("terminated", "completed")
                incoming = result.last_reply
                actor = "assistant" if actor == "user" else "user"
        return GenerationOutcome("truncated", "max_rounds")


def create_environment(plan: EnvironmentPlan) -> Environment:
    from agentinstruct.components import construct_component

    return cast(Environment, construct_component("environment", plan.type, plan))
