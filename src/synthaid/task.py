"""The definition of a conversation for an Environment to run."""

from collections.abc import Sequence
import dataclasses

from synthaid import agent
from synthaid import message


@dataclasses.dataclass(frozen=True)
class Step:
    """One part of a conversation, steered by its own instruction.

    Attributes:
        instruction: What should happen in this part. With a user
            simulator, only the simulator sees it. With a single agent, it
            is sent as the user message.
        max_turns: How many user and assistant exchanges this step adds.
            Ignored with a single agent, which always answers once. Must
            be at least 1.
    """

    instruction: str
    max_turns: int = 1

    def __post_init__(self) -> None:
        """Checks the step so that a run cannot fail on it later.

        Raises:
            ValueError: `max_turns` is less than 1.
        """
        if self.max_turns < 1:
            raise ValueError(f"max_turns must be at least 1: {self.max_turns=}")


@dataclasses.dataclass(eq=False)
class Task:
    """A conversation to generate: who takes part and how it should go.

    An Environment runs the task and appends every message the agents
    produce to `chat_history`. A Task is not frozen because its history
    grows. Give each Task its own agents, because one Agent serves one
    role in one conversation.

    Attributes:
        assistant: The agent whose replies are the trace.
        steps: The parts of the conversation, in order. At least one.
        user: The user simulator. None means each step's instruction is
            the user message.
        chat_history: The conversation so far. It may start with earlier
            messages for the run to build on. It holds no system messages,
            because each agent adds its own from its instructions.
    """

    assistant: agent.Agent
    steps: Sequence[Step]
    user: agent.Agent | None = None
    chat_history: list[message.Message] = dataclasses.field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        """Checks the task so that a run cannot fail on it later.

        Raises:
            ValueError: `steps` is empty, `user` is `assistant`, or
                `chat_history` contains a system message.
        """
        if not self.steps:
            raise ValueError("A task needs at least one step")
        if self.user is self.assistant:
            raise ValueError("user and assistant must be different agents")
        if any(item.role == "system" for item in self.chat_history):
            raise ValueError("chat_history must not contain system messages")
