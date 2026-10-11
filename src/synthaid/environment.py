"""Runs a Task: the exchange between the user simulator and the assistant."""

from collections.abc import Iterator, Sequence
import dataclasses

from synthaid import message
from synthaid import task as task_lib

_SWAPPED_ROLES: dict[message.Role, message.Role] = {
    "user": "assistant",
    "assistant": "user",
}


class Environment:
    """Runs tasks by passing messages between their agents.

    The whole interface is `run()`.
    """

    def run(self, task: task_lib.Task) -> None:
        """Runs every step of `task` and appends to its chat history.

        Loops through the steps. Every message a step yields is appended
        to `task.chat_history` straight away, so if an agent raises, the
        history keeps everything yielded before the error. When the
        assistant is the one that fails, the history ends with that turn's
        user message. Calling run() again runs all the steps again on top
        of the history so far.

        Args:
            task: The task to run. Its `chat_history` grows in place.

        Raises:
            exception.ToolError: An agent's tool call failed.
            openai.APIError: Any transport or server error.
        """
        view = _SimulatorView()
        for step in task.steps:
            for item in self._run_step(task, step, view):
                task.chat_history.append(item)

    def _run_step(
        self,
        task: task_lib.Task,
        step: task_lib.Step,
        view: "_SimulatorView",
    ) -> Iterator[message.Message]:
        """Runs the exchanges of one step and yields the messages to add.

        Works on its own copy of `task.chat_history`, so it gives the same
        result whether or not the caller has appended the yielded messages
        yet.

        With a single agent there is one exchange: the step instruction as
        a user message, then everything `assistant.run()` returned.
        `max_turns` is ignored.

        With a user simulator there are `max_turns` exchanges, and the
        simulator always speaks first. In each one:

        1. The simulator gets `view`, its own side of the conversation,
           brought up to date with the history and `_turn_note()` for
           this turn. Its final reply is yielded as a user message. Its
           tool calls and tool results stay in its view and its logs.
        2. The assistant gets the history as it is, with the step
           instruction and the step's start for its evaluator. Everything
           `assistant.run()` returned is yielded: accepted drafts with
           tool calls, their tool results, and the final reply.

        Args:
            task: The task the step belongs to.
            step: The step to run.
            view: The simulator's view, kept across the steps of one run.

        Yields:
            Each message to add to the history, in order.
        """
        history = list(task.chat_history)
        step_start = len(history)
        turns = 1 if task.user is None else step.max_turns
        for turn in range(1, turns + 1):
            if task.user is None:
                prompt = message.Message("user", step.instruction)
            else:
                replies = task.user.run(
                    view.prompt(history, _turn_note(step, turn))
                )
                view.add(replies)
                prompt = message.Message(
                    "user", replies[-1].content, reasoning=replies[-1].reasoning
                )
            history.append(prompt)
            yield prompt
            replies = task.assistant.run(
                history,
                instruction=step.instruction,
                context_start=step_start,
            )
            for item in replies:
                history.append(item)
                yield item


@dataclasses.dataclass
class _SimulatorView:
    """The user simulator's side of the conversation. It only grows.

    The simulator sees the chat history with the user and assistant roles
    swapped and without the assistant's tool calls and tool results. Each
    turn adds only what is new, so earlier notes stay where they were sent
    and every request continues the last one.

    Attributes:
        messages: Everything the simulator has been sent or has said.
        synced: How much of the chat history is already in `messages`.
    """

    messages: list[message.Message] = dataclasses.field(default_factory=list)
    synced: int = 0

    def prompt(
        self, history: Sequence[message.Message], note: str
    ) -> list[message.Message]:
        """Adds what is new in `history` and `note`, and returns the view.

        The new history is swapped by `_swapped()`. The note is merged
        into the last message when it is a user message the simulator has
        not seen yet, or added as a new user message otherwise. Merging
        keeps the roles alternating for servers that require it.

        Args:
            history: The task's chat history.
            note: The step instruction and turn number from `_turn_note`.

        Returns:
            A copy of the view to send to the simulator.
        """
        self.messages += _swapped(history[self.synced :])
        self.synced = len(history)
        last = self.messages[-1] if self.messages else None
        if last is not None and last.role == "user":
            merged = message.Message("user", f"{last.text}\n\n{note}")
            self.messages[-1] = merged
        else:
            self.messages.append(message.Message("user", note))
        return list(self.messages)

    def add(self, replies: Sequence[message.Message]) -> None:
        """Adds what the simulator returned, with its tool calls and results.

        Its final reply goes into the chat history as one user message,
        which the view already holds, so it is counted as synced.
        """
        self.messages += replies
        self.synced += 1


def _swapped(history: Sequence[message.Message]) -> list[message.Message]:
    """Returns history messages as the user simulator sees them.

    Drops the assistant's messages that have tool calls, and every tool
    result. Swaps the user and assistant roles.
    """
    return [
        message.Message(_SWAPPED_ROLES[item.role], item.text)
        for item in history
        if item.role != "tool" and not item.tool_calls
    ]


def _turn_note(step: task_lib.Step, turn: int) -> str:
    """Returns the simulator's note for one turn of `step`.

    The note gives the step instruction as the goal for this part of the
    conversation, says "turn k of n", and tells the simulator to build on
    what has been said instead of asking again for anything already
    answered. On the last turn it also asks the simulator to bring this
    part of the conversation to a close.

    Args:
        step: The step being run.
        turn: The turn number, starting at 1.
    """
    note = (
        "Simulator note: your goal for this part of the conversation: "
        f"{step.instruction}\n"
        f"This is turn {turn} of {step.max_turns}. Build on what has "
        "already been said, and do not ask again for anything the "
        "assistant has already answered."
    )
    if turn == step.max_turns:
        note += " This is the last turn, so bring this part to a close."
    return note
