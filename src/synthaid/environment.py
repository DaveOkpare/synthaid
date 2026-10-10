"""Runs a Task: the exchange between the user simulator and the assistant."""

from collections.abc import Iterator, Sequence

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
        for step in task.steps:
            for item in self._run_step(task, step):
                task.chat_history.append(item)

    def _run_step(
        self, task: task_lib.Task, step: task_lib.Step
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

        1. The simulator gets `_user_view()` of the history with
           `_turn_note()` for this turn. Its final reply is yielded as a
           user message. Its tool calls and tool results stay in its own
           logs.
        2. The assistant gets the history as it is. Everything
           `assistant.run()` returned is yielded: accepted drafts with
           tool calls, their tool results, and the final reply.

        Args:
            task: The task the step belongs to.
            step: The step to run.

        Yields:
            Each message to add to the history, in order.
        """
        history = list(task.chat_history)
        turns = 1 if task.user is None else step.max_turns
        for turn in range(1, turns + 1):
            if task.user is None:
                prompt = message.Message("user", step.instruction)
            else:
                view = _user_view(history, _turn_note(step, turn))
                reply = task.user.run(view)[-1]
                prompt = message.Message(
                    "user", reply.content, reasoning=reply.reasoning
                )
            history.append(prompt)
            yield prompt
            for item in task.assistant.run(history):
                history.append(item)
                yield item


def _user_view(
    history: Sequence[message.Message], note: str
) -> list[message.Message]:
    """Returns the history as the user simulator sees it.

    Drops the assistant's messages that have tool calls, and every tool
    result. Swaps the user and assistant roles. Then merges `note` into
    the last message when it is a user message, or adds the note as a new
    user message otherwise. Merging keeps the roles alternating for
    servers that require it.

    Args:
        history: The task's chat history.
        note: The step instruction and turn number from `_turn_note`.

    Returns:
        A new list. `history` is not changed.
    """
    view = [
        message.Message(_SWAPPED_ROLES[item.role], item.text)
        for item in history
        if item.role != "tool" and not item.tool_calls
    ]
    if view and view[-1].role == "user":
        merged = f"{view[-1].text}\n\n{note}"
        return [*view[:-1], message.Message("user", merged)]
    return [*view, message.Message("user", note)]


def _turn_note(step: task_lib.Step, turn: int) -> str:
    """Returns the simulator's note for one turn of `step`.

    The note gives the step instruction and says "turn k of n". On the
    last turn it also asks the simulator to bring this part of the
    conversation to a close.

    Args:
        step: The step being run.
        turn: The turn number, starting at 1.
    """
    note = (
        f"Simulator note: {step.instruction}\n"
        f"This is turn {turn} of {step.max_turns}."
    )
    if turn == step.max_turns:
        note += " This is the last turn, so bring this part to a close."
    return note
