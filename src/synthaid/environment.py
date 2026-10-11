"""Runs a Task: the exchange between the user simulator and the assistant."""

from collections.abc import Iterator, Sequence

from synthaid import message
from synthaid import task as task_lib

_SWAPPED_ROLES: dict[message.Role, message.Role] = {
    "user": "assistant",
    "assistant": "user",
}


def run(task: task_lib.Task) -> None:
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
    view = _swapped(task.chat_history)
    for step in task.steps:
        for item in _run_step(task, step, view):
            task.chat_history.append(item)


def _run_step(
    task: task_lib.Task,
    step: task_lib.Step,
    view: list[message.Message],
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

    1. `_turn_note()` is added to `view`, the simulator's side of the
       conversation, and the simulator runs on it. Its final reply is
       yielded as a user message. Its tool calls and tool results stay
       in its view and its logs.
    2. The assistant gets the history as it is. Everything
       `assistant.run()` returned is yielded: accepted drafts with
       tool calls, their tool results, and the final reply. The
       final reply is also added to `view`, swapped.

    Args:
        task: The task the step belongs to.
        step: The step to run.
        view: The simulator's view. It only grows, across the steps
            of one run, so each request continues the last one.

    Yields:
        Each message to add to the history, in order.
    """
    history = list(task.chat_history)
    turns = 1 if task.user is None else step.max_turns
    for turn in range(1, turns + 1):
        if task.user is None:
            prompt = message.Message("user", step.instruction)
        else:
            note = message.Message("user", _turn_note(step, turn))
            view.append(note)
            replies = task.user.run(view)
            view += replies
            prompt = message.Message(
                "user", replies[-1].content, reasoning=replies[-1].reasoning
            )
        history.append(prompt)
        yield prompt
        replies = task.assistant.run(history)
        view += _swapped(replies)
        for item in replies:
            history.append(item)
            yield item


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
