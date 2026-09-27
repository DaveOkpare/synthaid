"""Immutable execution inputs, with deterministic JSON serialization."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from types import MappingProxyType
from typing import Literal, cast

from agentinstruct.quality import Rubric

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
type FrozenJsonValue = (
    bool
    | int
    | float
    | str
    | tuple[FrozenJsonValue, ...]
    | Mapping[str, FrozenJsonValue]
    | None
)


def freeze(value: JsonValue) -> FrozenJsonValue:
    """Copy JSON data into recursively immutable containers."""
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def json_value(value: object) -> JsonValue:
    """Project plan dataclasses and immutable containers into plain JSON data."""
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Cannot serialize {type(value).__name__} as plan data")


def canonical_json(value: object) -> str:
    return json.dumps(
        json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def content_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TaskIdentity:
    id: str
    version: str
    digest: str


@dataclass(frozen=True)
class SeedOrigin:
    path: str
    record: int = 1


@dataclass(frozen=True)
class Seed:
    id: str
    data: Mapping[str, FrozenJsonValue]
    origin: SeedOrigin
    digest: str


@dataclass(frozen=True)
class ProviderPlan:
    id: str
    type: str
    api: str
    base_url: str | None
    api_key_env: str | None


@dataclass(frozen=True)
class ModelPlan:
    provider: str
    name: str
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class ScriptedResponse:
    content: str
    control: Literal["complete"] | None = None


@dataclass(frozen=True)
class ReviewerPlan:
    type: Literal["custom", "deterministic"]
    instruction: str
    max_revisions: int = 1
    accept_on_revision_exhaustion: bool = False
    checks: Mapping[str, Literal["nonempty_content"]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.max_revisions) is not int or self.max_revisions < 0:
            raise ValueError("Reviewer max_revisions must be a nonnegative integer")
        if type(self.accept_on_revision_exhaustion) is not bool:
            raise ValueError("Reviewer exhaustion fallback must be a Boolean")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        if self.type == "deterministic":
            if set(self.checks.values()) - {"nonempty_content"}:
                raise ValueError("Unknown deterministic Reviewer check")
        elif self.type != "custom" or self.checks:
            raise ValueError(
                "Custom Reviewers require a factory and no built-in checks"
            )


type JsonSchema = bool | Mapping[str, FrozenJsonValue]


@dataclass(frozen=True)
class ToolPlan:
    id: str
    description: str
    input_schema: JsonSchema
    output_schema: JsonSchema | None = None
    execution_errors: Literal["fail", "result"] = "fail"

    def __post_init__(self) -> None:
        if self.execution_errors not in {"fail", "result"}:
            raise ValueError("Tool execution_errors must be fail or result")
        for name in ("input_schema", "output_schema"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self, name, cast(JsonSchema, freeze(json_value(value)))
                )


@dataclass(frozen=True)
class AgentPlan:
    id: str
    target: bool
    model: ModelPlan
    base_instruction: str
    type: str = "model"
    responses: tuple[str | ScriptedResponse, ...] = ()
    reviewer: ReviewerPlan | None = None
    rubric: Rubric | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class EnvironmentPlan:
    type: str
    max_turns: int
    initiator: str = "user"
    max_rounds: int = 10
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class RuntimePlan:
    type: str = "local"


@dataclass(frozen=True)
class PlanProvenance:
    package_version: str
    python_version: str


@dataclass(frozen=True)
class VerifierPlan:
    type: Literal["custom", "deterministic"]
    rubric: Rubric
    timeout_seconds: float = 60.0
    checks: Mapping[str, Literal["nonempty_conversation", "generation_terminated"]] = (
        field(default_factory=dict)
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Verifier timeout must be finite and positive")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        if self.type == "deterministic":
            if set(self.checks) != {criterion.id for criterion in self.rubric.criteria}:
                raise ValueError("Deterministic checks must match every Criterion ID")
            if set(self.checks.values()) - {
                "nonempty_conversation",
                "generation_terminated",
            }:
                raise ValueError("Unknown deterministic Verifier check")
        elif self.type != "custom" or self.checks:
            raise ValueError(
                "Custom Verifiers require a factory and no built-in checks"
            )


@dataclass(frozen=True)
class RunPlan:
    """Inputs for one Trace attempt; execution assigns Run and Trace identities."""

    schema_version: str
    task: TaskIdentity
    seed: Seed
    variables: Mapping[str, FrozenJsonValue]
    providers: Mapping[str, ProviderPlan]
    agents: Mapping[str, AgentPlan]
    environment: EnvironmentPlan
    runtime: RuntimePlan
    provenance: PlanProvenance
    verifier: VerifierPlan | None = None
    tools: Mapping[str, ToolPlan] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", MappingProxyType(dict(self.tools)))

    @property
    def digest(self) -> str:
        return content_digest(self)

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a detached JSON-compatible snapshot, including the plan digest."""
        result = json_value(self)
        assert isinstance(result, dict)
        result["digest"] = self.digest
        return result

    def to_json(self) -> str:
        return canonical_json(self.to_dict())
