"""Immutable generation records shared by execution, storage, and consumers."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from agentinstruct.plans import FrozenJsonValue, VerifierPlan, freeze, json_value

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
class FunctionCall:
    name: str
    arguments: Mapping[str, FrozenJsonValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", immutable_data(self.arguments))


@dataclass(frozen=True)
class ToolCall:
    id: str
    function: FunctionCall
    type: Literal["function"] = "function"


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    name: str | None = None
    id: str = ""
    actor_id: str | None = None
    # A single-step completion proposal, effective only after Message acceptance.
    control: Literal["complete"] | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))


@dataclass(frozen=True)
class MessageCommit:
    message: Message
    turn_id: str
    timestamp: str
    step_id: str | None = None
    visibility: Literal["shared", "private"] = "shared"
    causal_message_id: str | None = None
    review_id: str | None = None
    review_exhausted: bool = False


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
class VerificationError:
    kind: Literal["execution", "malformed", "timeout"]
    exception: str
    message: str


@dataclass(frozen=True)
class VerificationAttempt:
    schema_version: str
    id: str
    trace_id: str
    sequence: int
    plan: VerifierPlan
    verifier: ComponentProvenance
    status: Literal["accepted", "rejected", "unverified"]
    score: float | None
    criteria: Mapping[str, bool]
    feedback: str
    started_at: str
    ended_at: str
    duration_seconds: float
    error: VerificationError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", MappingProxyType(dict(self.criteria)))


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
    verification: tuple[VerificationAttempt, ...] = ()
    selected_verification_id: str | None = None

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
