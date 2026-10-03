"""Read-only inspection of current Episodes and historical recorded runs."""

import unicodedata
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agentinstruct.episode import Episode, Message, json_data, parse_json

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


class Inspector:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=True)
        self.run: Mapping[str, Any] | None = None
        if self.path.is_dir() and (self.path / "manifest.json").is_file():
            self.run, self.traces = _load_run(self.path)
        elif self.path.is_dir() and not (self.path / "trace.json").is_file():
            self.run = {"path": str(self.path)}
            self.traces = tuple(
                Episode.load(source)
                for source in sorted(self.path.glob("*/trace.json"))
            )
        else:
            self.traces = (Episode.load(self.path),)

    def summary(self, *, trace_index: int | None = None) -> dict[str, Any]:
        if trace_index is None and self.run is not None:
            return {
                "kind": "run",
                "path": str(self.path),
                "manifest": json_data(self.run),
                "counts": dict(Counter(episode.status for episode in self.traces)),
                "traces": [
                    {"trace_id": e.id, "status": e.status, "path": str(e.path)}
                    for e in self.traces
                ],
            }
        return _trace_summary(self.traces[trace_index or 0])

    def view(
        self, name: str, *, trace_index: int = 0, participant: str | None = None
    ) -> dict[str, Any]:
        if name == "summary":
            return self.summary(trace_index=trace_index)
        if name not in VIEWS:
            raise ValueError("Unknown inspection view")
        episode = self.traces[trace_index]
        if name == "participant" and participant not in episode.metadata.get(
            "agents", {}
        ):
            raise ValueError("Unknown participant")
        return {
            "view": name,
            "trace_id": episode.id,
            **_view_content(episode, name, participant),
        }

    def render(
        self,
        view: str = "summary",
        *,
        trace_index: int | None = None,
        participant: str | None = None,
    ) -> str:
        data = (
            self.summary(trace_index=trace_index)
            if view == "summary"
            else self.view(view, trace_index=trace_index or 0, participant=participant)
        )
        heading = (
            f"{data.get('kind', view).title()} {data.get('trace_id', self.path.name)}"
        )
        return terminal_text(heading + "\n" + _render_content(data))


def _view_messages(
    episode: Episode, view: str, participant: str | None
) -> tuple[Message, ...]:
    messages = (
        episode.history(participant) if view == "participant" else episode.messages
    )
    return tuple(
        message
        for message in messages
        if view != "tools" or message.tool_calls or message.role == "tool"
    )


def _view_event(event: Mapping[str, Any], view: str) -> bool:
    kind = event["kind"]
    return (
        kind
        in {
            "proposal",
            "review_requested",
            "review_result",
            "rejection",
            "revision",
            "review_exhausted",
        }
        if view == "reviews"
        else "error" in kind or kind in {"cleanup_failure", "deadline"}
    )


def _evidence_view(episode: Episode, view: str) -> dict[str, Any]:
    if view == "verification":
        return {"attempts": json_data(episode.verification)}
    if view == "provenance":
        return {"run_plan": json_data(episode.metadata)}
    if view == "artifacts":
        return {"artifacts": _artifacts(episode)}
    return {
        "calls": _recorded_calls(episode),
        "accepted_continuations": [
            json_data(m.reasoning) for m in episode.messages if m.reasoning
        ],
    }


def _artifacts(episode: Episode) -> list[dict[str, Any]]:
    if episode.path is None:
        return []
    root = episode.path / "artifacts"
    if not root.exists():
        return []
    if root.is_symlink():
        raise ValueError("Artifacts directory must remain confined")
    return [
        {"path": str(path.relative_to(root)), "bytes": path.stat().st_size}
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    ]


def _load_run(root: Path) -> tuple[Mapping[str, Any], tuple[Episode, ...]]:
    manifest = parse_json(_confined(root / "manifest.json", root).read_text())
    entries = manifest.get("traces")
    if entries is None:
        entries = [
            parse_json(line)
            for line in _confined(root / "traces.jsonl", root).read_text().splitlines()
        ]
    episodes = [_run_entry(root, entry, manifest.get("run_id")) for entry in entries]
    identities = [episode.id for episode in episodes]
    paths = [episode.path for episode in episodes]
    if len(identities) != len(set(identities)) or len(paths) != len(set(paths)):
        raise ValueError("Run index has duplicate identities or paths")
    return manifest, tuple(episodes)


def _run_source(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Run index paths must be relative and confined")
    source = _confined(root / path, root)
    snapshot = source / "trace.json" if source.is_dir() else source
    _confined(snapshot, root)
    directory = snapshot.parent / "verification"
    if directory.exists():
        _confined(directory, root)
        for sidecar in directory.glob("*.json"):
            _confined(sidecar, root)
    return source


def _confined(path: Path, root: Path) -> Path:
    resolved = path.resolve(strict=True)
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("Run evidence escapes its root")
    return resolved


def _render_message(message: Mapping[str, Any]) -> str:
    calls = ", ".join(
        call["function"]["name"] for call in message.get("tool_calls", ())
    )
    label = message.get("actor_id") or message["role"]
    visibility = " [private]" if message.get("visibility") == "private" else ""
    return f"{label}{visibility}: {message['content']}" + (
        f"\n  Tools: {calls}" if calls else ""
    )


def _render_value(key: str, value: Any) -> str:
    if isinstance(value, Mapping):
        return (
            key
            + ":\n"
            + "\n".join("  " + _render_value(str(k), v) for k, v in value.items())
        )
    if isinstance(value, list):
        return (
            key
            + ":\n"
            + "\n".join(
                "  " + _render_value(str(i + 1), item) for i, item in enumerate(value)
            )
        )
    return f"{key}: {value}"


def terminal_text(value: str) -> str:
    return "".join(
        character
        if character in "\n\t" or not unicodedata.category(character).startswith("C")
        else f"\\u{ord(character):04x}"
        for character in value
    )


def _trace_summary(episode: Episode) -> dict[str, Any]:
    return {
        "kind": "trace",
        "trace_id": episode.id,
        "path": str(episode.path),
        "status": episode.status,
        "generation": json_data(episode.generation),
        "participants": list(episode.metadata.get("agents", {})),
        "messages": len(episode.messages),
        "events": len(episode.events),
        "task": json_data(episode.metadata.get("task", {})),
        "seed": json_data(episode.metadata.get("seed", {})),
        "selected_verification": json_data(episode.verification[-1])
        if episode.verification
        else None,
    }


def _view_content(
    episode: Episode, view: str, participant: str | None
) -> dict[str, Any]:
    if view in {"conversation", "participant", "tools"}:
        return {
            "messages": [
                json_data(m) for m in _view_messages(episode, view, participant)
            ]
        }
    if view in {"reviews", "failures"}:
        return {
            "events": [json_data(e) for e in episode.events if _view_event(e, view)]
        }
    return _evidence_view(episode, view)


def _recorded_calls(episode: Episode) -> list[dict[str, Any]]:
    calls = [
        json_data(event) for event in episode.events if event["kind"] == "model_call"
    ]
    calls.extend(
        {"kind": "verification", "data": json_data(attempt.get("events", {}))}
        for attempt in episode.verification
    )
    return calls


def _run_entry(root: Path, entry: Mapping[str, Any], run_id: Any) -> Episode:
    episode = Episode.load(_run_source(root, entry["path"]))
    if episode.id != entry["trace_id"]:
        raise ValueError("Run index has mismatched identities")
    if episode.metadata.get("run_id", run_id) != run_id:
        raise ValueError("Episode belongs to a different Run")
    return episode


def _render_content(data: Mapping[str, Any]) -> str:
    if "messages" in data and isinstance(data["messages"], list):
        return "\n".join(_render_message(message) for message in data["messages"])
    return "\n".join(
        _render_value(key, value)
        for key, value in data.items()
        if key not in {"kind", "view", "trace_id"}
    )
