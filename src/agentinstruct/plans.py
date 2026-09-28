"""Immutable execution inputs, with deterministic JSON serialization."""

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from types import MappingProxyType
from typing import ClassVar, Literal, cast

from pydantic import ConfigDict

from agentinstruct.quality import Criterion, Rubric

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
    format: Literal["json", "csv", "python"] = "json"


@dataclass(frozen=True)
class Seed:
    id: str
    data: Mapping[str, FrozenJsonValue]
    origin: SeedOrigin
    digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", freeze(json_value(self.data)))


@dataclass(frozen=True)
class ReasoningControls:
    """Portable requested reasoning behavior; model support is endpoint-specific."""

    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    summary: Literal["auto", "concise", "detailed"] | None = None

    def __post_init__(self) -> None:
        if self.effort not in {
            None,
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        }:
            raise ValueError("Unknown reasoning effort")
        if self.summary not in {None, "auto", "concise", "detailed"}:
            raise ValueError("Unknown reasoning summary mode")


type VllmMode = Literal[
    "json", "choice", "regex", "grammar", "json_object", "structural_tag"
]
type VllmModifier = Literal[
    "whitespace_pattern", "disable_any_whitespace", "disable_additional_properties"
]
type VllmControl = Literal[
    "effort", "thinking_token_budget", "include_reasoning", "enable_thinking"
]


@dataclass(frozen=True)
class VllmStructuredOutputs:
    """Current vLLM constraints; exactly one mode, with optional modifiers."""

    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    json: Mapping[str, JsonValue | FrozenJsonValue] | None = None
    choice: tuple[str, ...] | None = None
    regex: str | None = None
    grammar: str | None = None
    json_object: bool | None = None
    structural_tag: str | None = None
    whitespace_pattern: str | None = None
    disable_any_whitespace: bool | None = None
    disable_additional_properties: bool | None = None

    def __post_init__(self) -> None:
        modes = ("json", "choice", "regex", "grammar", "json_object", "structural_tag")
        if sum(getattr(self, name) is not None for name in modes) != 1:
            raise ValueError("Exactly one vLLM structured-output mode is required")
        if self.json_object is not None and self.json_object is not True:
            raise ValueError("json_object must be true when selected")
        for name in ("disable_any_whitespace", "disable_additional_properties"):
            if (
                getattr(self, name) is not None
                and type(getattr(self, name)) is not bool
            ):
                raise ValueError("vLLM modifiers must be Boolean")
        for name in ("regex", "grammar", "structural_tag", "whitespace_pattern"):
            if getattr(self, name) is not None and not isinstance(
                getattr(self, name), str
            ):
                raise ValueError("vLLM textual constraints must be strings")
        if self.choice is not None:
            if not self.choice or any(
                not isinstance(item, str) for item in self.choice
            ):
                raise ValueError("vLLM choices must contain strings")
            object.__setattr__(self, "choice", tuple(self.choice))
        if self.json is not None:
            canonical_json(self.json)
            object.__setattr__(self, "json", freeze(json_value(self.json)))

    @property
    def mode(self) -> VllmMode:
        for name in (
            "json",
            "choice",
            "regex",
            "grammar",
            "json_object",
            "structural_tag",
        ):
            if getattr(self, name) is not None:
                return name
        raise ValueError("Missing structured mode")


@dataclass(frozen=True)
class VllmChatTemplateKwargs:
    """Explicit Qwen-style template control; unknown model kwargs are rejected."""

    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    enable_thinking: bool | None = None

    def __post_init__(self) -> None:
        if self.enable_thinking is not None and type(self.enable_thinking) is not bool:
            raise ValueError("enable_thinking must be Boolean")


@dataclass(frozen=True)
class VllmOptions:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    structured_outputs: VllmStructuredOutputs | None = None
    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None
    ) = None
    thinking_token_budget: int | None = None
    include_reasoning: bool | None = None
    chat_template_kwargs: VllmChatTemplateKwargs | None = None

    def __post_init__(self) -> None:
        ReasoningControls(effort=self.reasoning_effort)
        if self.structured_outputs is not None and not isinstance(
            self.structured_outputs, VllmStructuredOutputs
        ):
            raise ValueError("structured_outputs requires typed vLLM constraints")
        if self.chat_template_kwargs is not None and not isinstance(
            self.chat_template_kwargs, VllmChatTemplateKwargs
        ):
            raise ValueError("chat_template_kwargs requires typed model controls")
        if self.thinking_token_budget is not None and (
            type(self.thinking_token_budget) is not int
            or self.thinking_token_budget < -1
        ):
            raise ValueError("thinking_token_budget must be an integer >= -1")
        if (
            self.include_reasoning is not None
            and type(self.include_reasoning) is not bool
        ):
            raise ValueError("include_reasoning must be Boolean")


@dataclass(frozen=True)
class VllmSurface:
    """Operator-declared capabilities for one independently tested API surface."""

    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    response_formats: tuple[Literal["text", "json_object", "json_schema"], ...] = (
        "text",
    )
    tool_choices: tuple[Literal["none", "auto", "required", "named"], ...] = ()
    parallel_tool_calls: bool = False
    reasoning: bool = False
    reasoning_controls: tuple[VllmControl, ...] = ()
    native_modes: tuple[VllmMode, ...] = ()
    structured_modifiers: tuple[VllmModifier, ...] = ()
    combinations: tuple[str, ...] = ()
    conformance: Literal["unverified", "passed"] = "unverified"
    report_digest: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            "response_formats": {"text", "json_object", "json_schema"},
            "tool_choices": {"none", "auto", "required", "named"},
            "reasoning_controls": {
                "effort",
                "thinking_token_budget",
                "include_reasoning",
                "enable_thinking",
            },
            "native_modes": {
                "json",
                "choice",
                "regex",
                "grammar",
                "json_object",
                "structural_tag",
            },
            "structured_modifiers": {
                "whitespace_pattern",
                "disable_any_whitespace",
                "disable_additional_properties",
            },
        }
        for name, values in allowed.items():
            value = tuple(getattr(self, name))
            if set(value) - values or len(value) != len(set(value)):
                raise ValueError("Unknown or duplicate vLLM capability")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "combinations", tuple(self.combinations))
        features = {str(mode) for mode in self.response_formats if mode != "text"}
        features.update("native:" + mode for mode in self.native_modes)
        if self.tool_choices:
            features.add("tools")
        if self.reasoning:
            features.add("reasoning")
        for combination in self.combinations:
            parts = combination.split("+")
            if (
                len(parts) != 2
                or "reasoning" not in parts
                or set(parts) - features
                or parts != sorted(set(parts))
            ):
                raise ValueError("Declare reasoning plus one supported feature")
        for name in ("reasoning", "parallel_tool_calls"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("vLLM capability switches must be Boolean")
        if self.parallel_tool_calls and not self.tool_choices:
            raise ValueError("Parallel Tool calls require Tool support")
        if self.conformance not in {"unverified", "passed"}:
            raise ValueError("Unknown conformance state")
        if self.conformance == "passed" and (
            self.report_digest is None
            or re.fullmatch(r"[0-9a-f]{64}", self.report_digest) is None
        ):
            raise ValueError("Passed conformance requires the recorded report SHA-256")


@dataclass(frozen=True)
class VllmProfile:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    vllm_version: str
    model: str
    model_revision: str
    chat_template: str
    server_flags: tuple[str, ...]
    hardware: str
    request_profile: str
    reasoning_parser: str | None = None
    tool_parser: str | None = None
    surfaces: Mapping[str, VllmSurface] = field(
        default_factory=lambda: {"chat_completions": VllmSurface()}
    )

    def __post_init__(self) -> None:
        for name in (
            "vllm_version",
            "model",
            "model_revision",
            "chat_template",
            "hardware",
            "request_profile",
        ):
            if (
                not isinstance(getattr(self, name), str)
                or not getattr(self, name).strip()
            ):
                raise ValueError("vLLM conformance provenance must be nonempty")
        if set(self.surfaces) - {"chat_completions", "responses"} or not self.surfaces:
            raise ValueError("Unknown or missing vLLM API surface")
        if any(not isinstance(value, VllmSurface) for value in self.surfaces.values()):
            raise ValueError("vLLM surfaces require typed capability declarations")
        if any(
            not isinstance(flag, str)
            or not flag.strip()
            or flag.split("=", 1)[0].split()[0]
            in {
                "--api-key",
                "--hf-token",
                "--token",
                "--auth-token",
                "--access-token",
                "--authorization",
                "--auth-header",
                "--hugging-face-hub-token",
                "--password",
                "--secret",
            }
            for flag in self.server_flags
        ):
            raise ValueError("Server provenance flags must not contain credentials")
        object.__setattr__(self, "surfaces", MappingProxyType(dict(self.surfaces)))
        object.__setattr__(self, "server_flags", tuple(self.server_flags))


@dataclass(frozen=True)
class CompatibleSurface:
    """Portable capabilities and retained evidence for one compatible endpoint."""

    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    response_formats: tuple[Literal["text", "json_object", "json_schema"], ...] = (
        "text",
    )
    tool_choices: tuple[Literal["none", "auto", "required", "named"], ...] = ()
    parallel_tool_calls: bool = False
    reasoning: bool = False
    reasoning_controls: tuple[Literal["effort", "summary"], ...] = ()
    combinations: tuple[
        Literal["json_object+reasoning", "json_schema+reasoning", "reasoning+tools"],
        ...,
    ] = ()
    conformance: Literal["unverified", "passed"] = "unverified"
    report_digest: str | None = None

    def __post_init__(self) -> None:
        allowed = {
            "response_formats": {"text", "json_object", "json_schema"},
            "tool_choices": {"none", "auto", "required", "named"},
            "reasoning_controls": {"effort", "summary"},
            "combinations": {
                "json_object+reasoning",
                "json_schema+reasoning",
                "reasoning+tools",
            },
        }
        for name, choices in allowed.items():
            value = tuple(getattr(self, name))
            if set(value) - choices or len(set(value)) != len(value):
                raise ValueError("Unknown or duplicate compatible capability")
            object.__setattr__(self, name, value)
        for name in ("reasoning", "parallel_tool_calls"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Compatible capability switches must be Boolean")
        if self.conformance not in {"unverified", "passed"}:
            raise ValueError("Unknown compatible conformance state")
        if self.conformance == "passed" and (
            self.report_digest is None
            or re.fullmatch(r"[0-9a-f]{64}", self.report_digest) is None
        ):
            raise ValueError("Passed conformance requires the recorded report SHA-256")


@dataclass(frozen=True)
class CompatibleEndpointProfile:
    __pydantic_config__: ClassVar[ConfigDict] = ConfigDict(extra="forbid", strict=True)
    model: str
    request_profile: str
    surfaces: Mapping[str, CompatibleSurface]

    def __post_init__(self) -> None:
        if not self.model.strip() or not self.request_profile.strip():
            raise ValueError("Compatible endpoint profiles need model/request identity")
        if not self.surfaces or set(self.surfaces) - {"chat_completions", "responses"}:
            raise ValueError("Unknown or missing compatible API surface")
        if any(
            not isinstance(value, CompatibleSurface) for value in self.surfaces.values()
        ):
            raise ValueError("Compatible surfaces require typed declarations")
        object.__setattr__(self, "surfaces", MappingProxyType(dict(self.surfaces)))


@dataclass(frozen=True)
class ProviderPlan:
    id: str
    type: str
    api: str
    base_url: str | None
    api_key_env: str | None
    retain_reasoning: bool = True
    vllm_profile: VllmProfile | None = None
    vllm_options: VllmOptions | None = None
    endpoint_profile: CompatibleEndpointProfile | None = None


@dataclass(frozen=True)
class ModelPlan:
    provider: str
    name: str
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning: ReasoningControls | None = None


@dataclass(frozen=True)
class StructuredOutputPlan:
    """Portable schema snapshot; the runtime Python class is never persisted."""

    name: str
    schema: Mapping[str, FrozenJsonValue]
    strict: bool = True
    description: str | None = None
    qualified_type: str | None = None
    fingerprint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema", freeze(json_value(self.schema)))
        fingerprint = content_digest(
            {
                "name": self.name,
                "schema": self.schema,
                "strict": self.strict,
                "description": self.description,
                "qualified_type": self.qualified_type,
            }
        )
        if self.fingerprint and self.fingerprint != fingerprint:
            raise ValueError(
                "Structured output fingerprint does not match its snapshot"
            )
        object.__setattr__(self, "fingerprint", fingerprint)


@dataclass(frozen=True)
class ScriptedResponse:
    content: str
    control: Literal["complete"] | None = None


@dataclass(frozen=True)
class ReviewerPlan:
    type: str
    instruction: str
    max_revisions: int = 1
    accept_on_revision_exhaustion: bool = False
    checks: Mapping[str, Literal["nonempty_content"]] = field(default_factory=dict)
    model: ModelPlan | None = None
    structured_output: StructuredOutputPlan | None = None

    def __post_init__(self) -> None:
        if type(self.max_revisions) is not int or self.max_revisions < 0:
            raise ValueError("Reviewer max_revisions must be a nonnegative integer")
        if type(self.accept_on_revision_exhaustion) is not bool:
            raise ValueError("Reviewer exhaustion fallback must be a Boolean")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        if (self.type == "model") != (
            self.model is not None and self.structured_output is not None
        ):
            raise ValueError("Model Reviewer requires a model and structured output")
        if self.type != "model" and (
            self.model is not None or self.structured_output is not None
        ):
            raise ValueError("Only model Reviewers accept model settings")
        if self.type == "deterministic":
            if set(self.checks.values()) - {"nonempty_content"}:
                raise ValueError("Unknown deterministic Reviewer check")
        elif self.checks:
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
    type: str = "custom"
    function: str | None = None
    agent_factory: str | None = None
    instruction: str | None = None
    agent_config: Mapping[str, FrozenJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_config", freeze(json_value(self.agent_config)))
        if self.type == "function":
            if (
                self.function is None
                or self.agent_factory is not None
                or self.instruction is not None
                or self.agent_config
            ):
                raise ValueError(
                    "Function Tool requires only an explicit function reference"
                )
        elif self.type == "agent":
            if (
                self.agent_factory is None
                or self.instruction is None
                or self.function is not None
            ):
                raise ValueError(
                    "Agent Tool requires an explicit factory and instruction"
                )
        elif (
            self.function is not None
            or self.agent_factory is not None
            or self.instruction is not None
            or self.agent_config
        ):
            raise ValueError("Tool adapter settings require function or agent type")
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
class StepAgentPlan:
    instruction: str
    appended_rubric: tuple[Criterion, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "appended_rubric", tuple(self.appended_rubric))


@dataclass(frozen=True)
class StepPlan:
    id: str
    agents: Mapping[str, StepAgentPlan]

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))


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
    component_digests: Mapping[str, str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "component_digests", MappingProxyType(dict(self.component_digests))
        )


@dataclass(frozen=True)
class VerifierPlan:
    type: str
    rubric: Rubric
    timeout_seconds: float = 60.0
    checks: Mapping[str, Literal["nonempty_conversation", "generation_terminated"]] = (
        field(default_factory=dict)
    )
    model: ModelPlan | None = None
    structured_output: StructuredOutputPlan | None = None
    instruction: str = "Evaluate the completed Trace against every declared Criterion."

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("Verifier timeout must be finite and positive")
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))
        if (self.type == "model") != (
            self.model is not None and self.structured_output is not None
        ):
            raise ValueError("Model Verifier requires a model and structured output")
        if self.type != "model" and (
            self.model is not None or self.structured_output is not None
        ):
            raise ValueError("Only model Verifiers accept model settings")
        if self.type == "deterministic":
            if set(self.checks) != {criterion.id for criterion in self.rubric.criteria}:
                raise ValueError("Deterministic checks must match every Criterion ID")
            if set(self.checks.values()) - {
                "nonempty_conversation",
                "generation_terminated",
            }:
                raise ValueError("Unknown deterministic Verifier check")
        elif self.checks:
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
    steps: tuple[StepPlan, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", MappingProxyType(dict(self.tools)))
        object.__setattr__(self, "steps", tuple(self.steps))

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
