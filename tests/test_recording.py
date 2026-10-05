"""Runner persists trace data when a Task finishes, fails or is cancelled."""

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import APIStatusError

from agentinstruct import Agent, Episode, Runner, Task
from agentinstruct.episode import Message
from agentinstruct.judge import Judgment
from tests.model_fixtures import Check, Transport, client, response


def test_episode_is_independent_data(tmp_path: Path) -> None:
    one, two = Episode(), Episode()
    one.path = tmp_path / "trace.json"
    one.messages.append(Message(role="user", content="Hello"))
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
            "user": Agent("model"),
            "assistant": Agent("model"),
        },
        input={"topic": "fractions"},
        verifier=Check(check=lambda messages: Judgment(True, "Correct")),
        max_turns=2,
    )
    task.episode.metadata = {"source": "prepared"}
    async with client(
        Transport(
            response("Explain fractions"),
            response(),
        )
    ) as borrowed:
        [episode] = await Runner([task], output_dir=tmp_path, client=borrowed).run()
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
    tasks = [Task(agents={"assistant": Agent("model")}) for _ in range(2)]
    original = getattr(os, operation)
    calls = 0

    def fail_second(*args: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk unavailable")
        original(*args)

    monkeypatch.setattr(os, operation, fail_second)
    async with client(Transport(response(), response())) as borrowed:
        with pytest.raises(OSError, match="disk unavailable"):
            await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
    previous, failing = (task.episode for task in tasks)
    assert previous.path is not None and failing.path is not None
    assert json.loads(previous.path.read_text())["messages"][0]["content"] == "Hello"
    assert not failing.path.exists()


@pytest.mark.asyncio
async def test_invalid_trace_data_is_not_published(tmp_path: Path) -> None:
    class InvalidMetadata:
        async def run(self, task: Task, *, client: Any = None) -> None:
            task.episode.metadata = {"value": float("nan")}

    task = Task(agents={"assistant": Agent("model")})
    with pytest.raises(ValueError, match="Out of range float values"):
        await Runner([task], output_dir=tmp_path, environment=InvalidMetadata()).run()
    assert task.episode.path is not None and not task.episode.path.exists()


@pytest.mark.asyncio
async def test_failure_preserves_current_trace_and_preceding_run(
    tmp_path: Path,
) -> None:
    judged: list[Sequence[Mapping[str, Any]]] = []

    def verify(messages: Sequence[Mapping[str, Any]]) -> bool:
        judged.append(messages)
        return True

    previous = Task(agents={"assistant": Agent("model")})
    failing = Task(
        agents={
            "user": Agent("model"),
            "assistant": Agent("model"),
        },
        verifier=Check(check=verify),
    )
    later = Task(agents={"assistant": Agent("model")})
    transport = Transport(
        response(),
        response("Explain fractions"),
        httpx.Response(500, json={"error": {"message": "failed"}}),
    )
    async with client(transport) as borrowed:
        with pytest.raises(APIStatusError):
            await Runner(
                [previous, failing, later], output_dir=tmp_path, client=borrowed
            ).run()
    assert not judged and later.episode.path is None
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

    async def wait(request: httpx.Request) -> httpx.Response:
        generated.set()
        await asyncio.Event().wait()
        return response("unreachable")

    @asynccontextmanager
    async def resource() -> Any:
        try:
            yield None
        finally:
            closed.append("application")

    task = Task(
        agents={
            "user": Agent("model"),
            "assistant": Agent("model"),
        }
    )

    async def application() -> None:
        transport = Transport(response("Explain fractions"), wait)
        async with resource(), client(transport) as borrowed:
            await Runner([task], output_dir=tmp_path, client=borrowed).run()

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
        async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
            raise OSError("verifier unavailable")

    task = Task(agents={"assistant": Agent("model")}, verifier=Failing())
    async with client(Transport(response())) as borrowed:
        with pytest.raises(OSError, match="verifier unavailable"):
            await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert task.episode.path is not None
    trace = json.loads(task.episode.path.read_text())
    assert trace["messages"][0]["content"] == "Hello" and trace["verification"] is None
