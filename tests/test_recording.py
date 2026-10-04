"""Runner persists trace data when a Task finishes, fails or is cancelled."""

import asyncio
import json
import os
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Episode, Judge, Runner, Task
from agentinstruct.episode import Message
from agentinstruct.judge import Judgment
from tests.test_generation import Learner, Reply


def test_episode_is_independent_data(tmp_path: Path) -> None:
    one, two = Episode(), Episode()
    one.path = tmp_path / "trace.json"
    one.messages.append(Message("user", "Hello"))
    assert one.id != two.id and not two.messages
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_runner_saves_messages_metadata_and_verification_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[Path] = []
    replace = os.replace

    def record(source: Path, destination: Path) -> None:
        replace(source, destination)
        published.append(destination)

    monkeypatch.setattr(os, "replace", record)
    task = Task(
        agents={
            "user": Agent(generator=Learner()),
            "assistant": Agent(generator=Reply()),
        },
        input={"topic": "fractions"},
        verifier=Judge(check=lambda messages: Judgment(True, "Correct")),
        max_turns=2,
    )
    task.episode.metadata = {"source": "prepared"}
    [episode] = await Runner([task], output_dir=tmp_path).run()
    assert episode.path is not None
    assert published == [episode.path]
    trace = json.loads(episode.path.read_text())
    assert trace["id"] == episode.id
    assert trace["metadata"] == {"source": "prepared", "input": {"topic": "fractions"}}
    assert [m["content"] for m in trace["messages"]] == ["Explain fractions", "Hello"]
    assert (
        trace["verification"]["passed"]
        and trace["verification"]["feedback"] == "Correct"
    )
    assert list(episode.path.parent.iterdir()) == [episode.path]


@pytest.mark.parametrize("operation", ["fsync", "replace"])
@pytest.mark.asyncio
async def test_failed_write_preserves_preceding_task_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    tasks = [Task(agents={"assistant": Agent(generator=Reply())}) for _ in range(2)]
    original = getattr(os, operation)
    calls = 0

    def fail_second(*args: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk unavailable")
        original(*args)

    monkeypatch.setattr(os, operation, fail_second)
    with pytest.raises(OSError, match="disk unavailable"):
        await Runner(tasks, output_dir=tmp_path).run()
    previous, failing = (task.episode for task in tasks)
    assert previous.path is not None and failing.path is not None
    assert json.loads(previous.path.read_text())["messages"][0]["content"] == "Hello"
    assert not failing.path.exists()


@pytest.mark.asyncio
async def test_invalid_trace_data_is_not_published(tmp_path: Path) -> None:
    class InvalidMetadata:
        async def run(self, task: Task, *, client: Any = None) -> None:
            task.episode.metadata = {"value": float("nan")}

    task = Task(agents={"assistant": Agent()})
    with pytest.raises(ValueError, match="Out of range float values"):
        await Runner([task], output_dir=tmp_path, environment=InvalidMetadata()).run()
    assert task.episode.path is not None and not task.episode.path.exists()


@pytest.mark.asyncio
async def test_failure_preserves_current_trace_and_preceding_run(
    tmp_path: Path,
) -> None:
    judged: list[Sequence[Message]] = []
    error = ValueError("generation failed")

    class Failing:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            raise error

    def verify(messages: Sequence[Message]) -> bool:
        judged.append(messages)
        return True

    previous = Task(agents={"assistant": Agent(generator=Reply())})
    failing = Task(
        agents={
            "user": Agent(generator=Learner()),
            "assistant": Agent(generator=Failing()),
        },
        verifier=Judge(check=verify),
    )
    later = Task(agents={"assistant": Agent(generator=Reply())})
    with pytest.raises(ValueError) as caught:
        await Runner([previous, failing, later], output_dir=tmp_path).run()
    assert caught.value is error and not judged and later.episode.path is None
    for task, content in ((previous, "Hello"), (failing, "Explain fractions")):
        assert task.episode.path is not None
        trace = json.loads(task.episode.path.read_text())
        assert trace["messages"][0]["content"] == content
    assert failing.episode.verification is None


@pytest.mark.asyncio
async def test_cancellation_preserves_snapshot_and_application_cleans_up(
    tmp_path: Path,
) -> None:
    generated = asyncio.Event()
    closed: list[str] = []

    class Waiting:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            generated.set()
            await asyncio.Event().wait()
            return Message("assistant", "unreachable")

    @asynccontextmanager
    async def resource() -> Any:
        try:
            yield None
        finally:
            closed.append("application")

    task = Task(
        agents={
            "user": Agent(generator=Learner()),
            "assistant": Agent(generator=Waiting()),
        }
    )

    async def application() -> None:
        async with resource():
            await Runner([task], output_dir=tmp_path).run()

    worker = asyncio.create_task(application())
    await generated.wait()
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert closed == ["application"] and task.episode.verification is None
    assert task.episode.path is not None
    assert (
        json.loads(task.episode.path.read_text())["messages"][0]["content"]
        == "Explain fractions"
    )


@pytest.mark.asyncio
async def test_verifier_error_leaves_recorded_conversation(tmp_path: Path) -> None:
    class Failing:
        async def evaluate(self, messages: Sequence[Message]) -> Judgment:
            raise OSError("verifier unavailable")

    task = Task(agents={"assistant": Agent(generator=Reply())}, verifier=Failing())
    with pytest.raises(OSError, match="verifier unavailable"):
        await Runner([task], output_dir=tmp_path).run()
    assert task.episode.path is not None
    trace = json.loads(task.episode.path.read_text())
    assert trace["messages"][0]["content"] == "Hello" and trace["verification"] is None
