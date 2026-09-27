"""Dataset export reads persisted terminal snapshots, never live execution state."""

from collections.abc import Iterable, Set
from pathlib import Path

from agentinstruct.plans import canonical_json
from agentinstruct.store import load_trace
from agentinstruct.traces import TraceStatus


def export_native(
    traces: Iterable[str | Path],
    destination: str | Path,
    *,
    statuses: Set[TraceStatus] = frozenset({"accepted"}),
) -> int:
    """Write full native Trace snapshots as JSONL, selecting statuses explicitly."""
    count = 0
    with Path(destination).open("w", encoding="utf-8") as stream:
        for path in traces:
            trace = load_trace(path)
            if trace.status in statuses:
                stream.write(canonical_json(trace) + "\n")
                count += 1
    return count
