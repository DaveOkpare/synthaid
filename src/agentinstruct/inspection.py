"""Read-only views over saved JSON traces."""

import json
import unicodedata
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

VIEWS = ("summary", "conversation", "participant", "verification", "provenance")


class Inspector:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=True)
        self.run = None
        self.paths: tuple[Path, ...]
        if self.path.is_file():
            self.paths = (self.path,)
        elif (self.path / "trace.json").is_file():
            self.paths = (self.path / "trace.json",)
        else:
            self.run = {"path": str(self.path)}
            self.paths = tuple(sorted(self.path.glob("*/trace.json")))
        self.traces = tuple(
            json.loads(p.read_text(encoding="utf-8")) for p in self.paths
        )
        if any(
            not isinstance(t, dict) or "id" not in t or "messages" not in t
            for t in self.traces
        ):
            raise ValueError("Unsupported trace format; expected id and messages")

    def summary(self, *, trace_index: int | None = None) -> dict[str, Any]:
        if trace_index is None and self.run is not None:
            return {
                "kind": "run",
                "path": str(self.path),
                "counts": dict(Counter(trace_status(t) for t in self.traces)),
                "traces": [
                    self.summary(trace_index=i) for i in range(len(self.traces))
                ],
            }
        trace = self.traces[trace_index or 0]
        return {
            "kind": "trace",
            "trace_id": trace["id"],
            "path": str(self.paths[trace_index or 0]),
            "status": trace_status(trace),
            "messages": len(trace["messages"]),
            "verification": trace.get("verification"),
            "metadata": trace.get("metadata", {}),
        }

    def view(
        self, name: str, *, trace_index: int = 0, participant: str | None = None
    ) -> dict[str, Any]:
        if name == "summary":
            return self.summary(trace_index=trace_index)
        if name not in VIEWS:
            raise ValueError("Unknown inspection view")
        trace = self.traces[trace_index]
        if name == "participant" and participant not in {
            m["role"] for m in trace["messages"]
        }:
            raise ValueError("Unknown participant")
        if name in {"conversation", "participant"}:
            content = {"messages": trace["messages"]}
        elif name == "verification":
            content = {"verification": trace.get("verification")}
        else:
            content = {"metadata": trace.get("metadata", {})}
        return {"view": name, "trace_id": trace["id"], **content}

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
        if isinstance(data.get("messages"), list):
            text = "\n".join(f"{m['role']}: {m['content']}" for m in data["messages"])
        else:
            text = json.dumps(data, allow_nan=False)
        return terminal_text(text)


def trace_status(trace: Mapping[str, Any]) -> str:
    result = trace.get("verification")
    if result is None:
        return "unverified"
    return "accepted" if result["passed"] else "rejected"


def terminal_text(value: str) -> str:
    return "".join(
        character
        if character in "\n\t" or not unicodedata.category(character).startswith("C")
        else f"\\u{ord(character):04x}"
        for character in value
    )
