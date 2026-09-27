"""Agent protocols and the Interaction acceptance boundary."""

from collections import deque
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import uuid4

from agentinstruct.plans import (
    AgentPlan,
    EnvironmentPlan,
    FrozenJsonValue,
    TaskIdentity,
)
from agentinstruct.quality import score_verdicts
from agentinstruct.review import (
    Reviewer,
    ReviewError,
    ReviewExhausted,
    ReviewRequest,
    ReviewResult,
)
from agentinstruct.store import TraceRecorder, timestamp
from agentinstruct.traces import (
    Event,
    GenerationOutcome,
    Message,
    MessageCommit,
    TraceSnapshot,
    immutable_data,
)


@dataclass(frozen=True)
class Observation:
    actor_id: str
    instruction: str
    messages: tuple[Message, ...]
    review_feedback: str | None = None


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
    if plan.type == "scripted":
        return ScriptedAgent(plan)
    raise ValueError(
        "Model Agent adapters are not implemented yet; configure a scripted Agent "
        "or supply an agent_factory to Runner"
    )


@dataclass(frozen=True)
class TaskContext:
    task: TaskIdentity
    seed_id: str
    variables: Mapping[str, FrozenJsonValue]
    max_turns: int
    max_rounds: int = 10
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "variables", immutable_data(self.variables))


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
    ) -> None:
        self._plan = plan
        self._agent = agent
        self._recorder = recorder
        self._reviewer = reviewer

    def _observation(self, feedback: str | None = None) -> Observation:
        return Observation(
            self._plan.id,
            self._plan.base_instruction,
            tuple(
                item.message
                for item in self._recorder.conversation
                if item.visibility == "shared" or item.message.actor_id == self._plan.id
            ),
            feedback,
        )

    def _event(self, kind: str, data: object, turn_id: str) -> None:
        self._recorder.event(
            Event(
                uuid4().hex,
                kind,
                timestamp(),
                immutable_data(data),
                self._plan.id,
                turn_id,
            )
        )

    def _proposal(self, proposal: Message, turn_id: str) -> Message:
        if (
            not isinstance(proposal, Message)
            or proposal.role not in {"assistant", "user"}
            or not isinstance(proposal.content, str)
        ):
            raise ValueError("Agent must return conversational Messages")
        if proposal.control not in {None, "complete"}:
            raise ValueError("Unknown Message control proposal")
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
        review_id = uuid4().hex
        request = ReviewRequest(
            self._plan.reviewer.instruction,
            self._plan.rubric,
            message,
            self._observation().messages,
            self._plan.base_instruction,
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
        self._recorder.require_open()
        if incoming is not None and not any(
            item.message == incoming for item in self._recorder.conversation
        ):
            raise ValueError("Incoming reply must reference an accepted Message")
        turn_id = uuid4().hex
        action = await self._agent.generate(self._observation())
        proposals = deque(action if isinstance(action, list) else [action])
        if not proposals:
            raise ValueError("Agent returned no Messages")
        last_reply: Message | None = None
        while proposals:
            message = self._proposal(proposals.popleft(), turn_id)
            revisions = 0
            review_exhausted = False
            while True:
                review_id, feedback = await self._review(message, turn_id)
                if feedback is None:
                    break
                assert self._plan.reviewer is not None
                if revisions >= self._plan.reviewer.max_revisions:
                    review_exhausted = (
                        self._plan.reviewer.accept_on_revision_exhaustion
                        and message.control is None
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
                revision = await self._agent.generate(self._observation(feedback))
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
                    causal_message_id=incoming.id if incoming else None,
                    review_id=review_id,
                    review_exhausted=review_exhausted,
                )
            )
            self._event("message_committed", {"message_id": message.id}, turn_id)
            last_reply = message
            if message.control == "complete":
                return TurnResult(message, terminated=True)
        assert last_reply is not None
        return TurnResult(last_reply)


class AgentHandle:
    """Trace-bound facade: Environments interact without recorder access."""

    def __init__(
        self,
        plan: AgentPlan,
        agent: Agent,
        recorder: TraceRecorder,
        reviewer: Reviewer | None = None,
    ) -> None:
        self._interaction = Interaction(plan, agent, recorder, reviewer)

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
            await interaction.turn()
        return GenerationOutcome("terminated", "completed")


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
    if plan.type == "dialogue":
        return DialogueEnvironment(plan.initiator)
    if plan.type == "single":
        return SingleAgentEnvironment()
    raise ValueError(f"Unknown Environment: {plan.type}")
