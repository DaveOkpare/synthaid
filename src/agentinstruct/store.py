"""Local durable Message Commits and self-contained terminal Trace snapshots."""

import json
import os
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from agentinstruct.failures import SafeDiagnostics
from agentinstruct.paths import output_path
from agentinstruct.plans import RunPlan, canonical_json, json_value
from agentinstruct.traces import (
    Event,
    MessageCommit,
    RunResult,
    TraceReference,
    TraceSnapshot,
    VerificationAttempt,
)


class PersistenceError(OSError):
    """A storage operation failed, distinct from component-owned I/O failures."""


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


def _write_text(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


class TraceRecorder:
    """One Trace's accepted Conversation and operational Events."""

    def __init__(
        self,
        path: Path,
        plan: RunPlan | None = None,
        *,
        diagnostics: SafeDiagnostics | None = None,
    ) -> None:
        self.path = path
        self.diagnostics = diagnostics or SafeDiagnostics(
            plan.providers.values() if plan else ()
        )
        self.conversation: list[MessageCommit] = []
        self.events: list[Event] = []
        self._sealed = False
        path.mkdir(parents=True)
        (path / "artifacts").mkdir()
        if plan is not None:
            write_json(path / "run-plan.json", self.diagnostics.data(plan.to_dict()))
        _write_text(path / "conversation.jsonl", "")
        _write_text(path / "events.jsonl", "")
        _sync_directory(path / "artifacts")
        _sync_directory(path)
        _sync_directory(path.parent)
        _sync_directory(path.parent.parent)

    def commit(self, commit: MessageCommit) -> MessageCommit:
        self.require_open()
        if self.diagnostics.data(commit) != json_value(commit):
            raise PersistenceError("Message Commit must be sanitized before acceptance")
        try:
            append_json(self.path / "conversation.jsonl", commit)
        except OSError as exc:
            raise PersistenceError("Message Commit persistence failed") from exc
        self.conversation.append(commit)
        return commit

    def event(self, event: Event) -> None:
        self.require_open()
        event = TypeAdapter(Event).validate_python(
            self.diagnostics.data(event, diagnostic=True)
        )
        try:
            append_json(self.path / "events.jsonl", event)
        except OSError as exc:
            raise PersistenceError("Event persistence failed") from exc
        finally:
            self.events.append(event)

    def seal(self, snapshot: TraceSnapshot) -> None:
        self.require_open()
        write_json(
            self.path / "trace.json",
            self.diagnostics.data(snapshot),
            replace_existing=False,
        )
        self._sealed = True

    def require_open(self) -> None:
        if self._sealed:
            raise RuntimeError("Trace generation is sealed")


class LocalRunStore:
    """Explicitly opened local storage; construction has no filesystem effects."""

    def __init__(self, root: str | Path = "runs") -> None:
        self.root = Path(root)

    def open_run(
        self,
        run_id: str,
        source_files: Mapping[str, str],
        *,
        diagnostics: SafeDiagnostics | None = None,
    ) -> Path:
        path = output_path(self.root) / run_id
        path.mkdir(parents=True)
        source_root = path / "source-task"
        source_root.mkdir()
        directories = {path, source_root}
        for relative, text in source_files.items():
            destination = source_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            directories.update(
                parent
                for parent in destination.parents
                if parent.is_relative_to(source_root)
            )
            _write_text(destination, diagnostics.text(text) if diagnostics else text)
        for directory in sorted(
            directories, key=lambda item: len(item.parts), reverse=True
        ):
            _sync_directory(directory)
        write_json(
            path / "manifest.json",
            {
                "schema_version": "1",
                "run_id": run_id,
                "status": "running",
                "started_at": timestamp(),
            },
        )
        _write_text(path / "traces.jsonl", "")
        _sync_directory(path)
        _sync_directory(path.parent)
        _sync_directory(path.parent.parent)
        return path

    def index_trace(self, path: Path, reference: TraceReference) -> None:
        """Publish a reference only after all terminal Trace evidence is durable."""
        if not (reference.path / "trace.json").is_file():
            raise OSError("Cannot index a Trace before its snapshot is sealed")
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
