"""Durability, sealed generation, failures, cancellation and immutable verification."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Episode, Judge, Runner, Task, Tool
from agentinstruct.episode import (
    FunctionCall,
    Message,
    PersistenceError,
    ToolCall,
    parse_json,
)
from tests.test_generation import Reply


@pytest.mark.parametrize(
    "text", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}', '{"a":Infinity}']
)
def test_strict_json_parser(text: str) -> None:
    with pytest.raises(ValueError):
        parse_json(text)


def test_open_preserves_identity_and_never_overwrites_existing_paths(
    tmp_path: Path,
) -> None:
    episode = Episode()
    identity = episode.id
    destination = tmp_path / identity
    episode.open(destination)
    assert episode.id == identity
    with pytest.raises(RuntimeError):
        episode.open(tmp_path / "different")
    with pytest.raises(FileExistsError):
        Episode().open(destination)
    with pytest.raises(AttributeError):
        episode.messages = ()  # type: ignore[misc]
    episode.append(Message("assistant", "accepted", actor_id="assistant"))
    episode.seal()
    with pytest.raises(RuntimeError):
        episode.append(Message("assistant", "late"))
    with pytest.raises(RuntimeError):
        episode.record("late")
    with pytest.raises(RuntimeError):
        episode.seal()


@pytest.mark.asyncio
async def test_reverification_is_append_only_and_failed_generation_cannot_promote(
    tmp_path: Path,
) -> None:
    episode = Episode()
    episode.open(tmp_path / "episode")
    episode.append(Message("assistant", "accepted", actor_id="assistant"))
    episode.seal("failed", "execution")
    snapshot = (tmp_path / "episode/trace.json").read_bytes()
    await episode.verify(Judge(check=lambda messages: True))
    await episode.verify(Judge(check=lambda messages: False))
    assert episode.status == "failed" and len(episode.verification) == 2
    assert Episode.load(tmp_path / "episode").status == "failed"
    assert (tmp_path / "episode/trace.json").read_bytes() == snapshot
    paths = list((tmp_path / "episode/verification").glob("*.json"))
    assert len(paths) == 2


@pytest.mark.asyncio
async def test_intent_append_fsync_failure_prevents_all_tool_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effects: list[str] = []

    async def effect(arguments: Mapping[str, Any]) -> dict[str, Any]:
        effects.append("effect")
        return {"ok": True}

    class Calling(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            return Message(
                "assistant", tool_calls=(ToolCall("call", FunctionCall("effect")),)
            )

    task = Task(agents={"assistant": Calling(tools=[Tool(effect)])})
    import agentinstruct.episode as recording

    original = recording._append_json

    def refuse(path: Path, value: Any) -> None:
        if path.name == "conversation.jsonl":
            raise PersistenceError("disk canary")
        original(path, value)

    monkeypatch.setattr(recording, "_append_json", refuse)
    with pytest.raises(PersistenceError):
        await Runner([task], output_dir=tmp_path).run()
    assert not effects and not task.episode.messages
    assert task.episode.status == "failed"


@pytest.mark.asyncio
async def test_segment_failure_stops_future_instructions_and_final_judging(
    tmp_path: Path,
) -> None:
    activated: list[str] = []
    judged: list[Sequence[Message]] = []

    class Failing(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            activated.append(history[0].content)
            raise ValueError("deliberate failure")

    def final_check(messages: Sequence[Message]) -> bool:
        judged.append(messages)
        return True

    task = Task(
        agents={"assistant": Failing()},
        segments=[
            {"name": name, "instructions": {"assistant": name}}
            for name in ("first", "future")
        ],
        verifier=Judge(check=final_check),
    )
    await Runner([task], output_dir=tmp_path).run()
    assert activated == ["\n\nfirst"] and not judged
    assert task.episode.status == "failed"
    assert [
        event["data"]["name"]
        for event in task.episode.events
        if event["kind"] == "segment_activated"
    ] == ["first"]


@pytest.mark.asyncio
async def test_task_deadline_truncates_and_preserves_partial_accepted_history(
    tmp_path: Path,
) -> None:
    class Waiting(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            await asyncio.Event().wait()
            return Message("assistant", "unreachable")

    task = Task(agents={"assistant": Waiting()}, timeout_seconds=0.01)
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.generation == {"state": "truncated", "reason": "timeout"}
    assert task.episode.sealed and not task.episode.messages


@pytest.mark.asyncio
async def test_application_owns_cleanup_after_environment_cancellation(
    tmp_path: Path,
) -> None:
    generated = asyncio.Event()
    closed: list[str] = []
    borrowed = object()

    class Waiting(Agent):
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

    task = Task(agents={"assistant": Waiting()})

    async def application() -> None:
        async with resource():
            await Runner([task], output_dir=tmp_path, client=borrowed).run()

    worker = asyncio.create_task(application())
    await generated.wait()
    worker.cancel()
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert closed == ["application"]
    assert task.episode.status == "failed" and task.episode.sealed


@pytest.mark.asyncio
async def test_cancellation_and_seal_failure_preserve_the_primary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Cancelled(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            raise asyncio.CancelledError()

    task = Task(agents={"assistant": Cancelled()})
    import agentinstruct.episode as recording

    original = recording.write_json

    def refuse(path: Path, value: Any) -> None:
        if path.name == "trace.json":
            raise PersistenceError("seal failure")
        original(path, value)

    monkeypatch.setattr(recording, "write_json", refuse)
    with pytest.raises(asyncio.CancelledError):
        await Runner([task], output_dir=tmp_path).run()
    assert task.episode.status == "failed"
    assert any(event["kind"] == "error" for event in task.episode.events)


@pytest.mark.asyncio
async def test_historical_episode_and_immutable_diagnostics(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures/compatibility/v0.1.0-reviewed-trace"
    episode = Episode.load(source)
    raw = json.loads((source / "trace.json").read_text())
    assert episode.id == raw["trace_id"] and episode.messages
    assert episode.verification and episode.status == "accepted"
    with pytest.raises(TypeError):
        episode.events[0]["kind"] = "mutated"  # type: ignore[index]
    episode.export(tmp_path / "historical.jsonl")
    assert "private" not in (tmp_path / "historical.jsonl").read_text()


@pytest.mark.asyncio
async def test_export_rejects_evidence_aliases_before_writing(tmp_path: Path) -> None:
    task = Task(agents={"assistant": Reply()})
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.path is not None
    snapshot = task.episode.path / "trace.json"
    before = snapshot.read_bytes()
    for destination in (snapshot, task.episode.path / "artifacts/new.jsonl"):
        with pytest.raises(ValueError):
            task.episode.export(destination)
    link = tmp_path / "alias.jsonl"
    link.symlink_to(snapshot)
    with pytest.raises(ValueError):
        task.episode.export(link)
    assert snapshot.read_bytes() == before


@pytest.mark.asyncio
async def test_final_judge_timeout_leaves_sealed_generation_unverified(
    tmp_path: Path,
) -> None:
    async def blocked(messages: Sequence[Message]) -> bool:
        await asyncio.Event().wait()
        return True

    task = Task(
        agents={"assistant": Reply()},
        verifier=Judge(check=blocked, timeout_seconds=0.01),
    )
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.sealed and task.episode.generation["state"] == "terminated"
    assert task.episode.status == "unverified"
    assert task.episode.verification[-1]["error"]["kind"] == "timeout"


@pytest.mark.asyncio
async def test_final_judge_cancellation_survives_sidecar_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()

    async def blocked(messages: Sequence[Message]) -> bool:
        started.set()
        await asyncio.Event().wait()
        return True

    task = Task(agents={"assistant": Reply()}, verifier=Judge(check=blocked))
    worker = asyncio.create_task(Runner([task], output_dir=tmp_path).run())
    await started.wait()
    snapshot = (tmp_path / task.episode.id / "trace.json").read_bytes()
    import agentinstruct.episode as recording

    def broken(path: Path, value: Any) -> None:
        raise PersistenceError("sidecar unavailable")

    monkeypatch.setattr(recording, "write_json", broken)
    worker.cancel()
    with pytest.raises(asyncio.CancelledError) as error:
        await worker
    assert isinstance(error.value.__cause__, PersistenceError)
    assert task.episode.sealed and not task.episode.verification
    assert (tmp_path / task.episode.id / "trace.json").read_bytes() == snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [OSError, ValueError])
async def test_final_verification_publication_failure_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[Exception]
) -> None:
    import agentinstruct.episode as recording

    original = recording.write_json

    def broken(path: Path, value: Any) -> None:
        if path.parent.name == "verification":
            raise failure("sidecar unavailable")
        original(path, value)

    monkeypatch.setattr(recording, "write_json", broken)
    task = Task(agents={"assistant": Reply()}, verifier=Judge(check=lambda m: True))
    with pytest.raises(failure, match="sidecar unavailable"):
        await Runner([task], output_dir=tmp_path).run()
    assert task.episode.sealed and not task.episode.verification


@pytest.mark.asyncio
async def test_actual_commit_fsync_failure_prevents_capability_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    effects: list[str] = []

    async def effect(arguments: Mapping[str, Any]) -> Any:
        effects.append("effect")
        return {}

    class Calling(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            return Message(
                "assistant", tool_calls=(ToolCall("call", FunctionCall("effect")),)
            )

    task = Task(agents={"assistant": Calling(tools=[Tool(effect)])})
    destination = tmp_path / task.episode.id
    conversation = destination / "conversation.jsonl"
    original = os.fsync

    def broken(descriptor: int) -> None:
        stat = os.fstat(descriptor)
        if (
            conversation.exists()
            and stat.st_size > 0
            and stat.st_ino == conversation.stat().st_ino
        ):
            raise OSError("fsync unavailable")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(PersistenceError):
        await Runner([task], output_dir=tmp_path).run()
    assert not effects and not task.episode.messages and task.episode.status == "failed"


@pytest.mark.asyncio
async def test_seal_publication_failure_preserves_partial_ledgers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:

    import os

    original = os.link

    def broken(source: Any, destination: Any) -> None:
        if Path(destination).name == "trace.json":
            raise OSError("publication unavailable")
        original(source, destination)

    monkeypatch.setattr(os, "link", broken)
    task = Task(agents={"assistant": Reply()})
    with pytest.raises(PersistenceError):
        await Runner([task], output_dir=tmp_path).run()
    assert (
        task.episode.status == "failed" and task.episode.messages[0].content == "Hello"
    )
    assert (tmp_path / task.episode.id / "conversation.jsonl").read_text()
    assert not (tmp_path / task.episode.id / "trace.json").exists()


@pytest.mark.parametrize(
    "message",
    [
        Message("user", "done", actor_id="user", control="complete"),
        Message("assistant", "wrong role", actor_id="user"),
        Message(
            "tool",
            "{}",
            actor_id="assistant",
            tool_call_id="missing",
            visibility="private",
        ),
    ],
)
def test_episode_append_rejects_unauthorized_records(
    message: Message, tmp_path: Path
) -> None:
    episode = Episode()
    episode.open(tmp_path / episode.id)
    with pytest.raises(ValueError):
        episode.append(message)
    assert not episode.messages


@pytest.mark.asyncio
async def test_standalone_historical_file_appends_reverification_beside_that_file(
    tmp_path: Path,
) -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures/compatibility/v0.1.0-reviewed-trace/trace.json"
    )
    source = tmp_path / "capture.json"
    source.write_bytes(fixture.read_bytes())
    generation = source.read_bytes()
    episode = Episode.load(source)
    await episode.verify(Judge(check=lambda messages: True))
    assert Episode.load(source).status == "accepted"
    assert list((tmp_path / "capture.json.verification").glob("*.json"))
    assert source.read_bytes() == generation


def test_peer_observation_strips_reasoning_from_shared_custom_messages(
    tmp_path: Path,
) -> None:
    episode = Episode()
    episode.open(tmp_path / episode.id)
    episode.append(
        Message(
            "assistant",
            "accepted",
            actor_id="assistant",
            reasoning=({"type": "reasoning", "private": "opaque"},),
        )
    )
    assert episode.history("assistant")[0].reasoning
    assert episode.history("user")[0].content == "accepted"
    assert not episode.history("user")[0].reasoning
    assert "opaque" not in str(episode.training_messages())


def test_open_failure_preserves_identity_and_in_memory_failure_evidence(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "existing"
    destination.mkdir()
    canary = destination / "canary"
    canary.write_text("original")
    episode = Episode()
    identity = episode.id
    with pytest.raises(FileExistsError):
        episode.open(destination)
    assert episode.id == identity and episode.status == "failed"
    assert episode.events[-1]["kind"] == "opening_error"
    assert canary.read_text() == "original"
    with pytest.raises(RuntimeError):
        episode.open(tmp_path / "another")


@pytest.mark.parametrize(
    "field,value",
    [
        ("generation", {"state": "invented", "reason": "invalid"}),
        ("events", "not an event list"),
    ],
)
def test_saved_episode_shape_is_locally_validated(
    field: str, value: Any, tmp_path: Path
) -> None:
    fixture = (
        Path(__file__).parent
        / "fixtures/compatibility/v0.1.0-reviewed-trace/trace.json"
    )
    data = json.loads(fixture.read_text())
    data[field] = value
    source = tmp_path / "trace.json"
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Invalid saved Episode"):
        Episode.load(source)
