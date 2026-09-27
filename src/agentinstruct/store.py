"""Local durable Message Commits and self-contained terminal Trace snapshots."""

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from agentinstruct.plans import RunPlan, canonical_json
from agentinstruct.traces import Event, MessageCommit, RunResult, TraceSnapshot


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: object) -> None:
    """Publish a whole JSON file only after its replacement is flushed."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def append_json(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class TraceRecorder:
    """One Trace's accepted Conversation and operational Events."""

    def __init__(self, path: Path, plan: RunPlan) -> None:
        self.path = path
        self.conversation: list[MessageCommit] = []
        self.events: list[Event] = []
        path.mkdir(parents=True)
        (path / "artifacts").mkdir()
        write_json(path / "run-plan.json", plan.to_dict())
        (path / "conversation.jsonl").touch()
        (path / "events.jsonl").touch()

    def commit(self, commit: MessageCommit) -> None:
        append_json(self.path / "conversation.jsonl", commit)
        self.conversation.append(commit)

    def event(self, event: Event) -> None:
        append_json(self.path / "events.jsonl", event)
        self.events.append(event)

    def seal(self, snapshot: TraceSnapshot) -> None:
        write_json(self.path / "trace.json", snapshot)


class LocalRunStore:
    """Explicitly opened local storage; construction has no filesystem effects."""

    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)

    def open_run(self, run_id: str, source_files: Mapping[str, str]) -> Path:
        path = self.root.resolve() / run_id
        path.mkdir(parents=True)
        source_root = path / "source-task"
        source_root.mkdir()
        for relative, text in source_files.items():
            destination = source_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(text, encoding="utf-8")
        write_json(
            path / "manifest.json",
            {
                "schema_version": "1",
                "run_id": run_id,
                "status": "running",
                "started_at": timestamp(),
            },
        )
        (path / "traces.jsonl").touch()
        return path

    def finish_run(self, result: RunResult) -> None:
        # The caller seals each complete snapshot before exposing its reference.
        for reference in result.traces:
            append_json(
                result.path / "traces.jsonl",
                {
                    "trace_id": reference.trace_id,
                    "seed_id": reference.seed_id,
                    "status": reference.status,
                    "path": str(reference.path.relative_to(result.path)),
                },
            )
        manifest = json.loads((result.path / "manifest.json").read_text())
        manifest.update(result.to_dict())
        manifest.update(status="finished", ended_at=timestamp())
        write_json(result.path / "manifest.json", manifest)


def load_trace(path: str | Path) -> TraceSnapshot:
    """Inspect a terminal Trace without a Runner or the original Task Package."""
    source = Path(path)
    if source.is_dir():
        source = source / "trace.json"
    return TypeAdapter(TraceSnapshot).validate_json(source.read_text(encoding="utf-8"))
