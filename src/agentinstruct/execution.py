"""Agent protocols and the Interaction acceptance boundary."""

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Protocol
from uuid import uuid4

from agentinstruct.plans import AgentPlan, FrozenJsonValue, TaskIdentity
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


class Agent(Protocol):
    async def generate(self, observation: Observation) -> Message | list[Message]: ...


class ScriptedAgent:
    """Deterministic literal responses, consumed once per interaction turn."""

    def __init__(self, plan: AgentPlan) -> None:
        self._responses = iter(plan.responses)

    async def generate(self, observation: Observation) -> Message:
        try:
            content = next(self._responses)
        except StopIteration as exc:
            raise ValueError("Scripted Agent has no remaining responses") from exc
        return Message(role="assistant", content=content)


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "variables", immutable_data(self.variables))


@dataclass(frozen=True)
class TurnResult:
    last_reply: Message
    terminated: bool = False


class Interaction:
    def __init__(self, plan: AgentPlan, agent: Agent, recorder: TraceRecorder) -> None:
        self._plan = plan
        self._agent = agent
        self._recorder = recorder

    async def turn(self, incoming: Message | None = None) -> TurnResult:
        if incoming is not None and not any(
            item.message == incoming for item in self._recorder.conversation
        ):
            raise ValueError("Incoming reply must reference an accepted Message")
        turn_id = uuid4().hex
        observation = Observation(
            self._plan.id,
            self._plan.base_instruction,
            tuple(
                item.message
                for item in self._recorder.conversation
                if item.visibility == "shared" or item.message.actor_id == self._plan.id
            ),
        )
        action = await self._agent.generate(observation)
        proposals = action if isinstance(action, list) else [action]
        if not proposals:
            raise ValueError("Agent returned no Messages")
        last_reply: Message | None = None
        for proposal in proposals:
            if (
                not isinstance(proposal, Message)
                or proposal.role not in {"assistant", "user"}
                or not isinstance(proposal.content, str)
            ):
                raise ValueError("Agent must return conversational Messages")
            message = replace(proposal, id=uuid4().hex, actor_id=self._plan.id)
            self._recorder.event(
                Event(
                    uuid4().hex,
                    "proposal",
                    timestamp(),
                    immutable_data(message),
                    self._plan.id,
                    turn_id,
                )
            )
            self._recorder.commit(
                MessageCommit(
                    message,
                    turn_id,
                    timestamp(),
                    causal_message_id=incoming.id if incoming else None,
                )
            )
            self._recorder.event(
                Event(
                    uuid4().hex,
                    "message_committed",
                    timestamp(),
                    {"message_id": message.id},
                    self._plan.id,
                    turn_id,
                )
            )
            last_reply = message
        assert last_reply is not None
        return TurnResult(last_reply)


class AgentHandle:
    """Trace-bound facade: Environments interact without recorder access."""

    def __init__(self, plan: AgentPlan, agent: Agent, recorder: TraceRecorder) -> None:
        self._interaction = Interaction(plan, agent, recorder)

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
