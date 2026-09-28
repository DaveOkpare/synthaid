"""Persisted-only Run discovery and read-only operator inspection."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TextIO

from pydantic import TypeAdapter

from agentinstruct.plans import FrozenJsonValue, JsonValue, json_value
from agentinstruct.store import load_trace, verification_directory
from agentinstruct.traces import (
    STATUSES,
    TraceSnapshot,
    TraceStatus,
    VerificationAttempt,
    immutable_data,
)


@dataclass(frozen=True)
class RecordedTrace:
    path: Path
    snapshot: TraceSnapshot
    recorded_status: TraceStatus | None


@dataclass(frozen=True)
class RecordedRun:
    path: Path
    run_id: str
    manifest: Mapping[str, FrozenJsonValue]
    traces: tuple[RecordedTrace, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest", immutable_data(self.manifest))
        object.__setattr__(self, "traces", tuple(self.traces))

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "kind": "run",
            "run_id": self.run_id,
            "path": str(self.path),
            "status": json_value(self.manifest.get("status")),
            "counts": {
                status: sum(item.snapshot.status == status for item in self.traces)
                for status in STATUSES
            },
            "recorded_index_counts": {
                status: sum(item.recorded_status == status for item in self.traces)
                for status in STATUSES
            },
            "manifest": json_value(self.manifest),
            "traces": [
                {
                    "trace_id": item.snapshot.trace_id,
                    "seed_id": item.snapshot.seed_id,
                    "status": item.snapshot.status,
                    "recorded_status": item.recorded_status,
                    "path": str(item.path),
                }
                for item in self.traces
            ],
        }


@dataclass(frozen=True)
class _IndexEntry:
    trace_id: str
    seed_id: str
    status: TraceStatus
    path: str


def load_run(path: str | Path) -> RecordedRun:
    """Discover ordered, confined Trace snapshots using the relative Run index."""
    root = Path(path).resolve(strict=True)
    manifest = json.loads(
        _confined(root / "manifest.json", root).read_text(encoding="utf-8")
    )
    if not isinstance(manifest, dict) or not isinstance(manifest.get("run_id"), str):
        raise ValueError("Run manifest must identify its Run")
    traces: list[RecordedTrace] = []
    identities: set[str] = set()
    destinations: set[Path] = set()
    for line in (
        _confined(root / "traces.jsonl", root).read_text(encoding="utf-8").splitlines()
    ):
        entry = TypeAdapter(_IndexEntry).validate_json(line)
        relative = Path(entry.path)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Run index Trace path must be relative and confined")
        source = _confined(root / relative, root)
        snapshot = source / "trace.json" if source.is_dir() else source
        _confined(snapshot, root)
        sidecars = verification_directory(snapshot)
        if sidecars.exists() or sidecars.is_symlink():
            _confined(sidecars, root)
            for attempt in sidecars.glob("*.json"):
                _confined(attempt, root)
        trace = load_trace(source)
        if (trace.run_id, trace.trace_id, trace.seed_id) != (
            manifest["run_id"],
            entry.trace_id,
            entry.seed_id,
        ):
            raise ValueError("Run index identity does not match its Trace")
        if trace.trace_id in identities or source in destinations:
            raise ValueError("Run index contains a duplicate Trace")
        identities.add(trace.trace_id)
        destinations.add(source)
        traces.append(RecordedTrace(source, trace, entry.status))
    return RecordedRun(root, manifest["run_id"], manifest, tuple(traces))


def _confined(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved == root:
        raise ValueError("Run evidence path escapes its Run")
    return resolved


class Inspector:
    """Read a Run directory, Trace directory or standalone Trace snapshot once."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=True)
        self.run = (
            load_run(self.path)
            if self.path.is_dir() and (self.path / "manifest.json").is_file()
            else None
        )
        self.traces = (
            self.run.traces
            if self.run is not None
            else (RecordedTrace(self.path, load_trace(self.path), None),)
        )

    def summary(self, *, trace_index: int | None = None) -> dict[str, JsonValue]:
        """Current Trace decisions and separately labelled historical Run evidence."""
        if trace_index is None and self.run is not None:
            return self.run.to_dict()
        record = self.traces[trace_index or 0]
        trace = record.snapshot
        selected = next(
            (
                item
                for item in trace.verification
                if item.id == trace.selected_verification_id
            ),
            None,
        )
        agents = trace.run_plan.get("agents", {})
        return {
            "kind": "trace",
            "run_id": trace.run_id,
            "trace_id": trace.trace_id,
            "seed_id": trace.seed_id,
            "path": str(record.path),
            "status": trace.status,
            "generation": json_value(trace.generation),
            "task": json_value(trace.task or trace.run_plan.get("task")),
            "seed": json_value(trace.seed_record or trace.run_plan.get("seed")),
            "participants": list(agents) if isinstance(agents, Mapping) else [],
            "messages": len(trace.conversation),
            "events": len(trace.events),
            "started_at": trace.started_at,
            "ended_at": trace.ended_at,
            "duration_seconds": trace.duration_seconds,
            "selected_verification": _verification_summary(selected),
            "latest_verification": _verification_summary(trace.verification[-1])
            if trace.verification
            else None,
            "reasoning": _reasoning_summary(trace),
        }

    def view(
        self,
        name: str,
        *,
        trace_index: int = 0,
        participant: str | None = None,
    ) -> dict[str, JsonValue]:
        """Return independent JSON data for an operator or participant view."""
        if name == "summary":
            return self.summary(trace_index=trace_index)
        if name not in VIEWS:
            raise ValueError(f"Unknown view: {name}")
        record = self.traces[trace_index]
        trace = record.snapshot
        result: dict[str, JsonValue] = {"view": name, "trace_id": trace.trace_id}
        if name in {"conversation", "participant", "tools"}:
            participants = _participants(trace)
            if name == "participant" and participant not in participants:
                raise ValueError(f"Unknown participant: {participant}")
            messages = trace.conversation
            if name == "participant":
                messages = tuple(
                    item
                    for item in messages
                    if item.visibility == "shared"
                    or item.message.actor_id == participant
                )
                messages = tuple(
                    replace(
                        item,
                        message=replace(
                            item.message,
                            role="tool"
                            if item.message.role == "tool"
                            else "assistant"
                            if item.message.actor_id == participant
                            else "user",
                        ),
                    )
                    for item in messages
                )
                result["participant"] = participant
            elif name == "tools":
                messages = tuple(
                    item
                    for item in messages
                    if item.message.tool_calls or item.message.role == "tool"
                )
                result["events"] = json_value(
                    tuple(
                        event for event in trace.events if event.kind.startswith("tool")
                    )
                )
            result["messages"] = json_value(messages)
            result["step_boundaries"] = json_value(
                tuple(event for event in trace.events if event.kind == "step_started")
            )
        elif name == "reviews":
            result["events"] = json_value(
                tuple(
                    event
                    for event in trace.events
                    if event.kind.startswith("review")
                    or event.kind in {"draft", "rejection", "revision"}
                )
            )
        elif name == "verification":
            result["selected_verification_id"] = trace.selected_verification_id
            result["attempts"] = json_value(trace.verification)
        elif name == "provenance":
            result.update(
                {
                    "run_plan": json_value(trace.run_plan),
                    "components": json_value(trace.components),
                    "task": json_value(trace.task),
                    "seed_record": json_value(trace.seed_record),
                    "started_at": trace.started_at,
                    "ended_at": trace.ended_at,
                    "duration_seconds": trace.duration_seconds,
                }
            )
        elif name == "failures":
            result["generation"] = json_value(trace.generation)
            result["events"] = json_value(
                tuple(
                    event
                    for event in trace.events
                    if "error" in event.kind or "failed" in event.kind
                )
            )
            result["verification_errors"] = [
                {"attempt_id": item.id, "error": json_value(item.error)}
                for item in trace.verification
                if item.error is not None
            ]
            if self.run is not None:
                result["run_error"] = json_value(self.run.manifest.get("error"))
        elif name == "artifacts":
            result["artifacts"] = _artifacts(record.path)
        elif name == "reasoning":
            result.update(_reasoning(trace))
        return result

    def render(
        self,
        name: str = "summary",
        *,
        trace_index: int | None = None,
        participant: str | None = None,
    ) -> str:
        """Render plain terminal text, escaping controls from persisted content."""
        if name == "summary":
            summary = self.summary(trace_index=trace_index)
            if summary["kind"] == "run":
                assert self.run is not None
                rows = [
                    f"Run {self.run.run_id}: {summary['status']}",
                    f"Current Trace counts: {json.dumps(summary['counts'])}",
                    "Recorded index counts: "
                    + json.dumps(summary["recorded_index_counts"]),
                ]
                if self.run.manifest.get("error") is not None:
                    rows.append(f"Run error: {self.run.manifest['error']}")
                rows += [
                    f"{i}. Trace {item.snapshot.trace_id}; "
                    f"Seed {item.snapshot.seed_id}; "
                    f"{item.snapshot.status} (recorded {item.recorded_status})"
                    for i, item in enumerate(self.run.traces, 1)
                ]
            else:
                trace = self.traces[trace_index or 0].snapshot
                rows = [
                    f"Trace {trace.trace_id}: {trace.status}",
                    f"Run {trace.run_id}; Seed {trace.seed_id}",
                    f"Generation: {trace.generation.state} ({trace.generation.reason})",
                    f"Messages: {len(trace.conversation)}; "
                    f"Events: {len(trace.events)}; "
                    f"Duration: {trace.duration_seconds:.3f}s",
                    f"Participants: {', '.join(_participants(trace))}",
                    f"Selected Verification: {_attempt_label(trace, selected=True)}",
                    f"Latest Verification: {_attempt_label(trace, selected=False)}",
                    f"Reasoning: {json.dumps(summary['reasoning'])}",
                ]
            return terminal_text("\n".join(rows))
        data = self.view(name, trace_index=trace_index or 0, participant=participant)
        rows = [f"Trace {data['trace_id']} — {name}"]
        if name in {"conversation", "participant", "tools"}:
            messages = data["messages"]
            assert isinstance(messages, list)
            step: JsonValue = ""
            for item in messages:
                assert isinstance(item, dict)
                message = item["message"]
                assert isinstance(message, dict)
                if item["step_id"] != step:
                    step = item["step_id"]
                    rows.append(f"Task Step: {step or '(single step)'}")
                exhausted = " REVIEW EXHAUSTED" if item["review_exhausted"] else ""
                rows.append(
                    f"{message['actor_id']} | {message['role']} | {item['visibility']}"
                    f" | turn {item['turn_id']}{exhausted}"
                )
                if message["content"]:
                    rows.append(str(message["content"]))
                if message["tool_calls"]:
                    rows.append(
                        "Tool calls: "
                        + json.dumps(message["tool_calls"], ensure_ascii=False)
                    )
                if message["tool_call_id"]:
                    rows.append(f"Tool result for: {message['tool_call_id']}")
            rows.append(
                "Step boundaries: "
                + json.dumps(data["step_boundaries"], ensure_ascii=False)
            )
            if name == "tools":
                events = data["events"]
                assert isinstance(events, list)
                rows.extend(
                    "Tool event: " + json.dumps(event, ensure_ascii=False)
                    for event in events
                )
        elif name in {"reviews", "failures"}:
            for key, value in data.items():
                if key not in {"view", "trace_id"}:
                    for item in value if isinstance(value, list) else [value]:
                        rows.append(f"{key}: " + json.dumps(item, ensure_ascii=False))
        else:
            rows.append(json.dumps(data, indent=2, ensure_ascii=False))
        return terminal_text("\n".join(rows))


VIEWS = (
    "summary",
    "conversation",
    "participant",
    "tools",
    "reviews",
    "verification",
    "provenance",
    "failures",
    "artifacts",
    "reasoning",
)


def _verification_summary(attempt: VerificationAttempt | None) -> JsonValue:
    if attempt is None:
        return None
    return {
        "id": attempt.id,
        "sequence": attempt.sequence,
        "status": attempt.status,
        "score": attempt.score,
        "error": json_value(attempt.error),
    }


def _reasoning(trace: TraceSnapshot) -> dict[str, JsonValue]:
    providers = trace.run_plan.get("providers", {})
    policies: list[JsonValue] = []
    if isinstance(providers, Mapping):
        policies.extend(
            {
                "scope": "generation",
                "provider_id": name,
                "retain_reasoning": json_value(plan.get("retain_reasoning")),
            }
            for name, plan in providers.items()
            if isinstance(plan, Mapping)
        )
    calls: list[JsonValue] = []
    sources = [("generation", None, trace.events)] + [
        ("verification", item.id, item.events) for item in trace.verification
    ]
    for attempt in trace.verification:
        if attempt.provider is not None:
            policies.append(
                {
                    "scope": "verification",
                    "attempt_id": attempt.id,
                    "provider_id": attempt.provider.id,
                    "retain_reasoning": attempt.provider.retain_reasoning,
                }
            )
    for scope, attempt_id, events in sources:
        for event in events:
            response = event.data
            evidence = response.get("reasoning")
            error = event.data.get("error")
            if not isinstance(evidence, Mapping) and isinstance(error, Mapping):
                failed_response = error.get("response")
                if isinstance(failed_response, Mapping):
                    response = failed_response
                    evidence = response.get("reasoning")
            if not isinstance(evidence, Mapping):
                continue
            returned, retained = evidence.get("returned"), evidence.get("retained")
            calls.append(
                {
                    "scope": scope,
                    "attempt_id": attempt_id,
                    "event_id": event.id,
                    "actor_id": event.actor_id,
                    "step_id": event.step_id,
                    "turn_id": event.turn_id,
                    "provider_id": json_value(event.data.get("provider")),
                    "returned": json_value(returned),
                    "retained": json_value(retained),
                    "state": "retained"
                    if retained is True
                    else "suppressed"
                    if returned is True
                    else "not returned",
                    "items": json_value(evidence.get("items", ()))
                    if retained is True
                    else [],
                    "usage": json_value(response.get("usage")),
                    "request_id": json_value(response.get("request_id")),
                    "model": json_value(response.get("model")),
                    "finish_state": json_value(response.get("finish_state")),
                    "latency_seconds": json_value(response.get("latency_seconds")),
                    "error_kind": json_value(error.get("kind"))
                    if isinstance(error, Mapping)
                    else None,
                    "requested": json_value(evidence.get("requested")),
                }
            )
    return {"policies": policies, "calls": calls}


def _reasoning_summary(trace: TraceSnapshot) -> dict[str, JsonValue]:
    evidence = _reasoning(trace)
    calls = evidence["calls"]
    assert isinstance(calls, list)
    return {
        "policies": evidence["policies"],
        "returned_calls": sum(
            isinstance(item, dict) and item["returned"] is True for item in calls
        ),
        "retained_calls": sum(
            isinstance(item, dict) and item["retained"] is True for item in calls
        ),
        "suppressed_calls": sum(
            isinstance(item, dict) and item["state"] == "suppressed" for item in calls
        ),
    }


def _participants(trace: TraceSnapshot) -> tuple[str, ...]:
    agents = trace.run_plan.get("agents")
    return tuple(agents) if isinstance(agents, Mapping) else ()


def _attempt_label(trace: TraceSnapshot, *, selected: bool) -> str:
    attempt = (
        next(
            (
                item
                for item in trace.verification
                if item.id == trace.selected_verification_id
            ),
            None,
        )
        if selected
        else (trace.verification[-1] if trace.verification else None)
    )
    return (
        f"{attempt.id}: {attempt.status} (score={attempt.score})" if attempt else "none"
    )


def terminal_text(text: str) -> str:
    """Make recorded external text safe to write to a terminal."""
    return "".join(
        char
        if char == "\n" or char.isprintable()
        else char.encode("unicode_escape").decode("ascii")
        for char in text
    )


def _artifacts(path: Path) -> list[JsonValue]:
    if path.is_file():
        if (
            path.name != "trace.json"
            or not (path.parent / "conversation.jsonl").is_file()
        ):
            return []
        path = path.parent
    root = path / "artifacts"
    if not root.is_dir() or root.is_symlink():
        return []
    items: list[JsonValue] = []
    for directory, _, files in root.walk(follow_symlinks=False):
        for name in sorted(files):
            source = directory / name
            if source.is_file() and not source.is_symlink():
                items.append(
                    {
                        "path": source.relative_to(root).as_posix(),
                        "size_bytes": source.stat().st_size,
                    }
                )
    return sorted(items, key=lambda item: str(item))


class InspectionSession:
    """Small read-only navigation model; commands change only this session's view."""

    HELP = (
        "Commands: run, trace N (1-based), next, previous, summary, conversation, "
        "participant ID, tools, reviews, verification, provenance, failures, "
        "artifacts, reasoning, "
        "page N, more, back, help, quit. Views are operator-wide except participant ID."
    )

    def __init__(self, inspector: Inspector, *, page_size: int = 40) -> None:
        if page_size < 1:
            raise ValueError("page_size must be positive")
        self.inspector = inspector
        self.trace_index: int | None = None if inspector.run is not None else 0
        self.view = "summary"
        self.participant: str | None = None
        self.page = 0
        self.page_size = page_size
        self.closed = False

    def render(self) -> str:
        text = self.inspector.render(
            self.view, trace_index=self.trace_index, participant=self.participant
        )
        lines = text.splitlines()
        pages = max(1, (len(lines) + self.page_size - 1) // self.page_size)
        self.page = min(self.page, pages - 1)
        start = self.page * self.page_size
        return (
            "\n".join(lines[start : start + self.page_size])
            + f"\n[page {self.page + 1}/{pages}]"
        )

    def execute(self, command: str) -> str:
        parts = command.strip().split()
        if not parts:
            return self.render()
        verb, *arguments = parts
        try:
            if verb == "quit" and not arguments:
                self.closed = True
                return "Inspection closed."
            if verb == "help" and not arguments:
                return self.HELP
            if verb in {"more", "back", "page"}:
                if verb == "page" and len(arguments) == 1:
                    self.page = max(0, int(arguments[0]) - 1)
                elif verb in {"more", "back"} and not arguments:
                    self.page = max(0, self.page + (1 if verb == "more" else -1))
                else:
                    raise ValueError("Use page N, more or back")
                return self.render()
            if verb == "run" and not arguments and self.inspector.run is not None:
                self.trace_index, self.view = None, "summary"
            elif verb == "summary" and not arguments:
                self.view = "summary"
            elif verb == "trace" and len(arguments) == 1:
                index = int(arguments[0]) - 1
                if not 0 <= index < len(self.inspector.traces):
                    raise ValueError("Trace number is out of range")
                self.trace_index, self.view = index, "summary"
            elif verb in {"next", "previous"} and not arguments:
                index = (-1 if self.trace_index is None else self.trace_index) + (
                    1 if verb == "next" else -1
                )
                if not 0 <= index < len(self.inspector.traces):
                    raise ValueError("No further Trace in that direction")
                self.trace_index, self.view = index, "summary"
            elif verb in VIEWS and (
                len(arguments) == 1 if verb == "participant" else not arguments
            ):
                participant = arguments[0] if verb == "participant" else None
                self.inspector.view(
                    verb, trace_index=self.trace_index or 0, participant=participant
                )
                self.trace_index, self.view, self.participant = (
                    self.trace_index or 0,
                    verb,
                    participant,
                )
            else:
                raise ValueError("Unknown command; type help for navigation")
            self.page = 0
            return self.render()
        except (ValueError, IndexError) as exc:
            return terminal_text(f"{exc}")


def run_terminal(
    inspector: Inspector,
    input_stream: TextIO,
    output_stream: TextIO,
    *,
    trace_index: int | None = None,
    view: str = "summary",
    participant: str | None = None,
) -> None:
    """Run the line-oriented terminal UI; EOF and Ctrl-C close it without effects."""
    session = InspectionSession(inspector)
    session.trace_index, session.view, session.participant = (
        0 if trace_index is None and view != "summary" else trace_index,
        view,
        participant,
    )
    print(session.HELP, file=output_stream)
    print(session.render(), file=output_stream)
    while not session.closed:
        print("inspect> ", end="", file=output_stream, flush=True)
        try:
            command = input_stream.readline()
        except KeyboardInterrupt:
            break
        if not command:
            break
        print(session.execute(command), file=output_stream)
