"""Local durable Message Commits and self-contained terminal Trace snapshots."""

import json
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from agentinstruct.plans import RunPlan, canonical_json
from agentinstruct.traces import (
    Event,
    MessageCommit,
    RunResult,
    TraceReference,
    TraceSnapshot,
    VerificationAttempt,
)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_json(path: Path, value: object, *, replace_existing: bool = True) -> None:
    """Publish a whole JSON file only after its replacement is flushed."""
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if replace_existing:
            temporary.replace(path)
        else:
            # Atomic publication that fails instead of replacing immutable evidence.
            os.link(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def append_json(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(canonical_json(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


class TraceRecorder:
    """One Trace's accepted Conversation and operational Events."""

    def __init__(self, path: Path, plan: RunPlan | None = None) -> None:
        self.path = path
        self.conversation: list[MessageCommit] = []
        self.events: list[Event] = []
        self._sealed = False
        path.mkdir(parents=True)
        (path / "artifacts").mkdir()
        if plan is not None:
            write_json(path / "run-plan.json", plan.to_dict())
        (path / "conversation.jsonl").touch()
        (path / "events.jsonl").touch()

    def commit(self, commit: MessageCommit) -> None:
        self.require_open()
        append_json(self.path / "conversation.jsonl", commit)
        self.conversation.append(commit)

    def event(self, event: Event) -> None:
        self.require_open()
        append_json(self.path / "events.jsonl", event)
        self.events.append(event)

    def seal(self, snapshot: TraceSnapshot) -> None:
        self.require_open()
        write_json(self.path / "trace.json", snapshot, replace_existing=False)
        self._sealed = True

    def require_open(self) -> None:
        if self._sealed:
            raise RuntimeError("Trace generation is sealed")


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
        _sync_directory(path)
        _sync_directory(path.parent)
        return path

    def index_trace(self, path: Path, reference: TraceReference) -> None:
        """Publish a reference only after all terminal Trace evidence is durable."""
        # Retain newly created Trace/verification directories as well as the
        # already-fsynced snapshot and sidecar files before publishing discovery.
        _sync_directory(reference.path)
        _sync_directory(reference.path.parent)
        append_json(
            path / "traces.jsonl",
            {
                "trace_id": reference.trace_id,
                "seed_id": reference.seed_id,
                "status": reference.status,
                "path": str(reference.path.relative_to(path)),
            },
        )
        _sync_directory(path)

    def finish_run(self, result: RunResult) -> None:
        manifest = json.loads((result.path / "manifest.json").read_text())
        manifest.update(result.to_dict())
        manifest.update(ended_at=timestamp())
        write_json(result.path / "manifest.json", manifest)


def verification_directory(path: str | Path) -> Path:
    """Scope sidecars to their snapshot while preserving the Trace directory layout."""
    source = Path(path)
    if source.is_dir():
        source = source / "trace.json"
    if source.name == "trace.json":
        return source.parent / "verification"
    return source.with_name(f"{source.name}.verification")


def load_trace(
    path: str | Path, *, verification_id: str | None = None
) -> TraceSnapshot:
    """Inspect a terminal Trace without a Runner or the original Task Package."""
    source = Path(path)
    if source.is_dir():
        source = source / "trace.json"
    trace = TypeAdapter(TraceSnapshot).validate_json(source.read_text(encoding="utf-8"))
    sidecars = (
        TypeAdapter(VerificationAttempt).validate_json(item.read_text(encoding="utf-8"))
        for item in verification_directory(source).glob("*.json")
    )
    by_id: dict[str, VerificationAttempt] = {}
    for attempt in (*trace.verification, *sidecars):
        if attempt.trace_id != trace.trace_id:
            raise ValueError("Verification attempt belongs to a different Trace")
        if attempt.id in by_id and by_id[attempt.id] != attempt:
            raise ValueError("Conflicting copies of immutable Verification attempt")
        by_id[attempt.id] = attempt
    attempts = tuple(sorted(by_id.values(), key=lambda attempt: attempt.sequence))
    valid = [attempt for attempt in attempts if attempt.status != "unverified"]
    selected = valid[-1] if valid else None
    if verification_id is not None:
        selected = next((item for item in valid if item.id == verification_id), None)
        if selected is None:
            raise ValueError(
                "Selected Verification must name an existing valid attempt"
            )
    status = trace.status
    if status not in {"invalid", "failed"} and trace.generation.state != "failed":
        status = selected.status if selected else "unverified"
    return replace(
        trace,
        status=status,
        verification=attempts,
        selected_verification_id=selected.id if selected else None,
    )
