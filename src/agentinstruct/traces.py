"""Immutable generation records shared by execution, storage, and consumers."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from agentinstruct.plans import FrozenJsonValue, freeze, json_value

type TraceStatus = Literal["invalid", "failed", "unverified", "rejected", "accepted"]
STATUSES: tuple[TraceStatus, ...] = (
    "invalid",
    "failed",
    "unverified",
    "rejected",
    "accepted",
)


def immutable_data(value: object) -> Mapping[str, FrozenJsonValue]:
    data = json_value(value)
    if not isinstance(data, dict):
        raise TypeError("Expected a JSON object")
    return cast(Mapping[str, FrozenJsonValue], freeze(data))


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    id: str = ""
    actor_id: str | None = None


@dataclass(frozen=True)
class MessageCommit:
    message: Message
    turn_id: str
    timestamp: str
    step_id: str | None = None
    visibility: Literal["shared", "private"] = "shared"
    causal_message_id: str | None = None


@dataclass(frozen=True)
class Event:
    id: str
    kind: str
    timestamp: str
    data: Mapping[str, FrozenJsonValue] = field(default_factory=dict)
    actor_id: str | None = None
    turn_id: str | None = None
    step_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", immutable_data(self.data))


@dataclass(frozen=True)
class GenerationOutcome:
    state: Literal["terminated", "truncated", "failed"]
    reason: str


@dataclass(frozen=True)
class ComponentProvenance:
    kind: str
    reference: str
    digest: str | None


@dataclass(frozen=True)
class TraceSnapshot:
    schema_version: str
    run_id: str
    trace_id: str
    seed_id: str
    status: TraceStatus
    generation: GenerationOutcome
    run_plan: Mapping[str, FrozenJsonValue]
    conversation: tuple[MessageCommit, ...]
    events: tuple[Event, ...]
    components: tuple[ComponentProvenance, ...]
    started_at: str
    ended_at: str
    duration_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_plan", immutable_data(self.run_plan))


@dataclass(frozen=True)
class TraceReference:
    trace_id: str
    seed_id: str
    status: TraceStatus
    path: Path


@dataclass(frozen=True)
class RunResult:
    run_id: str
    path: Path
    traces: tuple[TraceReference, ...]
    counts: Mapping[TraceStatus, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "path": str(self.path),
            "traces": [
                {
                    "trace_id": item.trace_id,
                    "seed_id": item.seed_id,
                    "status": item.status,
                    "path": str(item.path),
                }
                for item in self.traces
            ],
            "counts": dict(self.counts),
        }
