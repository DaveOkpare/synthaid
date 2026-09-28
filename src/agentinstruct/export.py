"""Dataset export reads persisted terminal snapshots, never live execution state."""

from collections.abc import Iterable, Mapping, Set
from pathlib import Path

from agentinstruct.paths import normalized_name, output_path
from agentinstruct.plans import JsonValue, canonical_json, json_value
from agentinstruct.store import load_trace, verification_directory
from agentinstruct.traces import TraceStatus


def _export_paths(
    traces: Iterable[str | Path], destination: str | Path
) -> tuple[tuple[Path, ...], Path]:
    sources = tuple(Path(source) for source in traces)
    output = output_path(destination)
    protected: list[Path] = []
    for source in sources:
        resolved = source.resolve(strict=True)
        if resolved.is_dir():
            protected.append(resolved)
            resolved = resolved / "trace.json"
        elif not resolved.is_file():
            raise ValueError(
                f"Export source must be a Trace file or directory: {source}"
            )
        protected.extend([resolved, verification_directory(source).resolve()])
        if (
            resolved.name == "trace.json"
            and (resolved.parent / "conversation.jsonl").is_file()
        ):
            protected.append(resolved.parent)
        # A standalone snapshot protects itself and its sidecars. A Trace inside
        # a Run also protects the Run index, source snapshot, and sibling Traces.
        for parent in resolved.parents:
            if (parent / "manifest.json").is_file() and (
                parent / "traces.jsonl"
            ).is_file():
                protected.append(parent)
                break
    normalized_output = Path(normalized_name(str(output)).casefold())
    if any(
        normalized_output.is_relative_to(Path(normalized_name(str(path)).casefold()))
        for path in protected
    ):
        raise ValueError(
            "Export destination cannot overwrite source Run, Trace, "
            "or Verification evidence"
        )
    return sources, output


def export_native(
    traces: Iterable[str | Path],
    destination: str | Path,
    *,
    statuses: Set[TraceStatus] = frozenset({"accepted"}),
    verification_id: str | None = None,
) -> int:
    """Write full native Trace snapshots as JSONL, selecting statuses explicitly."""
    sources, output = _export_paths(traces, destination)
    count = 0
    with output.open("w", encoding="utf-8") as stream:
        for path in sources:
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
    sources, output = _export_paths(traces, destination)
    count = 0
    with output.open("w", encoding="utf-8") as stream:
        for path in sources:
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
