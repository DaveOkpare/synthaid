"""Writes finished tasks: training records, and a directory per run."""

from collections.abc import Iterable, Mapping, Sequence
import datetime
import json
import os
import pathlib
from typing import Any
import uuid

from synthaid import agent
from synthaid import message
from synthaid import task as task_lib


def to_record(task: task_lib.Task) -> dict[str, Any]:
    """Returns the task's conversation as one Chat Completions record.

    The record is {"messages": [...], "tools": [...]}. The messages are
    the assistant's system message followed by `chat_history`, in the
    Chat Completions shape. Reasoning is kept as `reasoning_content` on
    the messages that have it, and structured content is JSON text.
    "tools" holds the assistant's tool definitions and is left out when
    there are none.

    Args:
        task: A task that `environment.run()` has run.

    Returns:
        A dict that `json.dumps` can write as is.
    """
    system = message.Message("system", task.assistant.instructions)
    record: dict[str, Any] = {
        "messages": [_wire(item) for item in [system, *task.chat_history]]
    }
    tools = [item.to_chat_completions() for item in task.assistant.tools]
    if tools:
        record["tools"] = tools
    return record


def write_jsonl(
    tasks: Iterable[task_lib.Task], path: str | os.PathLike[str]
) -> None:
    """Appends one record per task to the JSON Lines file at `path`.

    The file is created when it does not exist. Text is written as UTF-8,
    not as escapes.

    Args:
        tasks: Tasks that `environment.run()` has run.
        path: The file to append to.
    """
    with open(path, "a", encoding="utf-8") as file:
        for item in tasks:
            file.write(json.dumps(to_record(item), ensure_ascii=False))
            file.write("\n")


def save(task: task_lib.Task, root: str | os.PathLike[str]) -> pathlib.Path:
    """Saves the task's exchange and every agent's logs in a new directory.

    The directory is created under `root` and named after the current
    time plus a random suffix, so every call gets its own. It holds:

    - exchange.json: `to_record(task)`.
    - logs/assistant.json and logs/user.json: each agent's `logs`, with
      rejected drafts, critiques and reasoning. user.json is left out
      when the task has no user simulator.
    - logs/assistant-evaluator.json and logs/user-evaluator.json: the
      logs of an agent's evaluator when that evaluator is itself an
      Agent, such as an LLMJudge.

    Messages are in the Chat Completions shape, with reasoning kept as
    `reasoning_content`. Files are indented JSON in UTF-8.

    Args:
        task: The task to save. It may have failed partway, since logs
            keep everything up to an error.
        root: The directory to create the task's directory in. It is
            created when it does not exist.

    Returns:
        The new directory.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    directory = pathlib.Path(root) / f"{stamp}-{uuid.uuid4().hex[:8]}"
    (directory / "logs").mkdir(parents=True)
    _write_json(directory / "exchange.json", to_record(task))
    agents = {"assistant": task.assistant}
    if task.user is not None:
        agents["user"] = task.user
    for role, member in agents.items():
        _write_json(directory / "logs" / f"{role}.json", _logs(member))
        if isinstance(member.evaluator, agent.Agent):
            path = directory / "logs" / f"{role}-evaluator.json"
            _write_json(path, _logs(member.evaluator))
    return directory


def _logs(member: agent.Agent) -> list[dict[str, Any]]:
    """Returns an agent's logs in the Chat Completions shape."""
    return [_wire(item) for item in member.logs]


def _write_json(
    path: pathlib.Path, data: Sequence[Any] | Mapping[str, Any]
) -> None:
    """Writes `data` to `path` as indented UTF-8 JSON."""
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _wire(item: message.Message) -> dict[str, Any]:
    """Returns one message in the Chat Completions shape, with reasoning."""
    wire: dict[str, Any] = dict(item.to_chat_completions())
    if item.reasoning is not None:
        wire["reasoning_content"] = item.reasoning
    return wire
