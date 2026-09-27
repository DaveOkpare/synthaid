"""Dataset export reads persisted terminal snapshots, never live execution state."""

from collections.abc import Iterable, Mapping, Set
from pathlib import Path

from agentinstruct.plans import JsonValue, canonical_json, json_value
from agentinstruct.store import load_trace
from agentinstruct.traces import TraceStatus


def export_native(
    traces: Iterable[str | Path],
    destination: str | Path,
    *,
    statuses: Set[TraceStatus] = frozenset({"accepted"}),
    verification_id: str | None = None,
) -> int:
    """Write full native Trace snapshots as JSONL, selecting statuses explicitly."""
    count = 0
    with Path(destination).open("w", encoding="utf-8") as stream:
        for path in traces:
            trace = load_trace(path, verification_id=verification_id)
            if trace.status in statuses:
                stream.write(canonical_json(trace) + "\n")
                count += 1
    return count


def export_openai(
    traces: Iterable[str | Path],
    destination: str | Path,
    *,
    statuses: Set[TraceStatus] = frozenset({"accepted"}),
    verification_id: str | None = None,
) -> int:
    """Write target-oriented training Messages from selected persisted Traces."""
    count = 0
    with Path(destination).open("w", encoding="utf-8") as stream:
        for path in traces:
            trace = load_trace(path, verification_id=verification_id)
            if trace.status not in statuses or not trace.conversation:
                continue
            agents = trace.run_plan.get("agents")
            if not isinstance(agents, Mapping):
                raise ValueError("Trace Run Plan must declare its Agents")
            targets = [
                actor_id
                for actor_id, plan in agents.items()
                if isinstance(plan, Mapping) and plan.get("target") is True
            ]
            if len(targets) != 1:
                raise ValueError("Trace Run Plan must contain exactly one Target Agent")
            target = targets[0]
            messages: list[dict[str, JsonValue]] = []
            for commit in trace.conversation:
                message = commit.message
                if commit.visibility == "private" and message.actor_id != target:
                    continue
                if message.actor_id not in agents:
                    raise ValueError("Trace Message must name a declared Agent")
                projected: dict[str, JsonValue] = {
                    "role": "tool"
                    if message.role == "tool"
                    else "assistant"
                    if message.actor_id == target
                    else "user",
                    "content": message.content,
                }
                if message.name is not None:
                    projected["name"] = message.name
                if message.tool_calls:
                    projected["tool_calls"] = json_value(message.tool_calls)
                if message.tool_call_id is not None:
                    projected["tool_call_id"] = message.tool_call_id
                messages.append(projected)
            if messages:
                stream.write(canonical_json({"messages": messages}) + "\n")
                count += 1
    return count
