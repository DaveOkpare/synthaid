"""Read-only views over saved JSON traces."""

import json
import unicodedata
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

VIEWS = ("summary", "conversation", "verification", "metadata")


class Inspector:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=True)
        source = self.path / "trace.json" if self.path.is_dir() else self.path
        self.is_run = not source.is_file()
        self.paths = (
            tuple(sorted(self.path.glob("*/trace.json"))) if self.is_run else (source,)
        )
        self.traces = tuple(
            json.loads(p.read_text(encoding="utf-8")) for p in self.paths
        )
        if any(
            not isinstance(t, dict) or "id" not in t or "messages" not in t
            for t in self.traces
        ):
            raise ValueError("Unsupported trace format; expected id and messages")

    def summary(self, *, trace_index: int | None = None) -> dict[str, Any]:
        if trace_index is not None or not self.is_run:
            return self._trace_summary(trace_index or 0)
        traces = [self._trace_summary(i) for i in range(len(self.traces))]
        return {
            "kind": "run",
            "path": str(self.path),
            "counts": dict(Counter(t["status"] for t in traces)),
            "traces": traces,
        }

    def _trace_summary(self, index: int) -> dict[str, Any]:
        trace = self.traces[index]
        return {
            "kind": "trace",
            "trace_id": trace["id"],
            "path": str(self.paths[index]),
            "status": trace_status(trace),
            "messages": len(trace["messages"]),
            "verification": trace.get("verification"),
            "metadata": trace.get("metadata", {}),
        }

    def view(
        self, name: str = "summary", *, trace_index: int | None = None
    ) -> dict[str, Any]:
        if name == "summary":
            return self.summary(trace_index=trace_index)
        if name not in VIEWS:
            raise ValueError("Unknown inspection view")
        trace = self.traces[trace_index or 0]
        key = "messages" if name == "conversation" else name
        default: dict[str, Any] | None = {} if name == "metadata" else None
        return {"view": name, "trace_id": trace["id"], key: trace.get(key, default)}

    def render(self, view: str = "summary", *, trace_index: int | None = None) -> str:
        data = self.view(view, trace_index=trace_index)
        if isinstance(data.get("messages"), list):
            text = "\n".join(f"{m['role']}: {m['content']}" for m in data["messages"])
        else:
            text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
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
