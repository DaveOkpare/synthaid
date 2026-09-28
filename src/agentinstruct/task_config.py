"""Strict authoring schema for built-in generation Task Packages."""

from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from agentinstruct.components import component_selector
from agentinstruct.paths import portable_name, seed_glob, unique_names
from agentinstruct.plans import (
    CompatibleEndpointProfile,
    JsonValue,
    VllmOptions,
    VllmProfile,
    canonical_json,
    json_value,
    validate_provider_url,
)
from agentinstruct.quality import Criterion, Rubric
from agentinstruct.steps import CONTROL_TOOLS

Identifier = Annotated[
    str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$"), AfterValidator(portable_name)
]
VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
NonemptyString = Annotated[str, Field(min_length=1)]


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TaskConfig(ConfigModel):
    id: Identifier
    version: NonemptyString
    steps: list[Identifier] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, steps: list[str]) -> list[str]:
        unique_names(steps, "Task Step identifiers")
        return steps


class SeedSourceConfig(ConfigModel):
    path: NonemptyString
    id_variable: VariableName | None = None
    schema_path: NonemptyString | None = Field(default=None, alias="schema")
    glob: Annotated[str, AfterValidator(seed_glob)] | None = None


class ProviderConfig(ConfigModel):
    type: Literal["openai", "openai-compatible", "vllm"]
    api: Literal["responses", "chat_completions"] | None = None
    base_url: str | None = None
    api_key_env: VariableName | None = None
    retain_reasoning: bool = True
    vllm_profile: VllmProfile | None = None
    vllm_options: VllmOptions | None = None
    endpoint_profile: CompatibleEndpointProfile | None = None

    @field_validator("endpoint_profile", mode="before")
    @classmethod
    def parse_endpoint_profile(cls, value: object) -> CompatibleEndpointProfile | None:
        return (
            None
            if value is None
            else TypeAdapter(CompatibleEndpointProfile).validate_json(
                canonical_json(value)
            )
        )

    @field_validator("vllm_profile", mode="before")
    @classmethod
    def parse_vllm_profile(cls, value: object) -> VllmProfile | None:
        return (
            None
            if value is None
            else TypeAdapter(VllmProfile).validate_json(canonical_json(value))
        )

    @field_validator("vllm_options", mode="before")
    @classmethod
    def parse_vllm_options(cls, value: object) -> VllmOptions | None:
        return (
            None
            if value is None
            else TypeAdapter(VllmOptions).validate_json(canonical_json(value))
        )

    @field_serializer("vllm_profile", "vllm_options", "endpoint_profile")
    def serialize_vllm(
        self, value: VllmProfile | VllmOptions | CompatibleEndpointProfile | None
    ) -> JsonValue:
        return json_value(value)

    @model_validator(mode="after")
    def validate_vllm(self, info: ValidationInfo) -> Self:
        if self.endpoint_profile is not None:
            if self.type != "openai-compatible":
                raise ValueError("Generic endpoint profiles require openai-compatible")
            surface = self.endpoint_profile.surfaces.get(self.api or "chat_completions")
            if surface is None or (
                self.api == "responses" and surface.conformance != "passed"
            ):
                raise ValueError(
                    "Selected compatible surface has no conformance declaration"
                )
        if self.type == "vllm":
            if self.vllm_profile is None or self.base_url is None:
                raise ValueError("vLLM requires an explicit profile and base URL")
            vllm_surface = self.vllm_profile.surfaces.get(
                self.api or "chat_completions"
            )
            if vllm_surface is None or (
                self.api == "responses"
                and vllm_surface.conformance != "passed"
                and not (info.context or {}).get("vllm_conformance_probe", False)
            ):
                raise ValueError("Selected vLLM surface has no conformance declaration")
        elif self.vllm_profile is not None or self.vllm_options is not None:
            raise ValueError("vLLM options and profile require a vLLM Provider")
        return self

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        return validate_provider_url(value)


class ReasoningConfig(ConfigModel):
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = None
    summary: Literal["auto", "concise", "detailed"] | None = None


class ModelConfig(ConfigModel):
    provider: Identifier
    name: NonemptyString
    temperature: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(gt=0)] | None = None
    reasoning: ReasoningConfig | None = None


class ModelOverride(ConfigModel):
    provider: Identifier | None = None
    name: NonemptyString | None = None
    temperature: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(gt=0)] | None = None
    reasoning: ReasoningConfig | None = None


class ScriptedResponseConfig(ConfigModel):
    content: str
    control: Literal["complete"] | None = None


class ReviewerConfig(ConfigModel):
    type: Annotated[
        str, AfterValidator(lambda value: component_selector("reviewer", value))
    ]
    model: ModelOverride = Field(default_factory=ModelOverride)
    max_revisions: Annotated[int, Field(ge=0)] = 1
    accept_on_revision_exhaustion: bool = False
    checks: dict[Identifier, Literal["nonempty_content"]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if self.type != "model" and self.model.model_fields_set:
            raise ValueError("Only model Reviewers accept model settings")
        return self


class AgentConfig(ConfigModel):
    target: bool
    model: ModelOverride = Field(default_factory=ModelOverride)
    type: Annotated[
        str, AfterValidator(lambda value: component_selector("agent", value))
    ] = "model"
    responses: list[str | ScriptedResponseConfig] = Field(default_factory=list)
    reviewer: ReviewerConfig | None = None
    tools: list[Identifier] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_script(self) -> Self:
        if self.type == "scripted" and not self.responses:
            raise ValueError("scripted Agents require at least one response")
        if self.type != "scripted" and self.responses:
            raise ValueError("responses require a scripted Agent")
        return self


class EnvironmentConfig(ConfigModel):
    type: Annotated[
        str, AfterValidator(lambda value: component_selector("environment", value))
    ]
    max_turns: Annotated[int, Field(gt=0)] = 1
    initiator: Literal["user", "assistant"] = "user"
    max_rounds: Annotated[int, Field(gt=0)] = 10
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if self.type == "dialogue" and "max_turns" in self.model_fields_set:
            raise ValueError("dialogue uses max_rounds to bound participant pairs")
        return self


class RuntimeConfig(ConfigModel):
    type: Literal["local"]


class CriterionConfig(ConfigModel):
    id: Identifier
    weight: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1.0
    description: str = ""


class RubricConfig(ConfigModel):
    criteria: list[CriterionConfig]
    threshold: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 1.0

    def to_rubric(self) -> Rubric:
        return Rubric(
            tuple(Criterion(c.id, c.weight, c.description) for c in self.criteria),
            self.threshold,
        )

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        self.to_rubric()
        return self


class StepRubricConfig(ConfigModel):
    """Only Criteria append; the Agent's base threshold remains authoritative."""

    criteria: list[CriterionConfig]

    def to_criteria(self) -> tuple[Criterion, ...]:
        return Rubric(
            tuple(Criterion(c.id, c.weight, c.description) for c in self.criteria)
        ).criteria

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        self.to_criteria()
        return self


class VerifierConfig(ConfigModel):
    type: Annotated[
        str, AfterValidator(lambda value: component_selector("verifier", value))
    ]
    model: ModelOverride = Field(default_factory=ModelOverride)
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 60.0
    checks: dict[
        Identifier, Literal["nonempty_conversation", "generation_terminated"]
    ] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_model(self) -> Self:
        if self.type != "model" and self.model.model_fields_set:
            raise ValueError("Only model Verifiers accept model settings")
        return self


class ToolConfig(ConfigModel):
    type: Annotated[
        str, AfterValidator(lambda value: component_selector("tool", value))
    ] = "custom"
    description: NonemptyString
    input_schema: dict[str, JsonValue] | bool
    output_schema: dict[str, JsonValue] | bool | None = None
    execution_errors: Literal["fail", "result"] = "fail"

    function: str | None = None
    agent_factory: str | None = None
    instruction: str | None = None
    agent_config: dict[str, JsonValue] = Field(default_factory=dict)


class PackageConfig(ConfigModel):
    schema_version: Literal["1"]
    task: TaskConfig
    seed: SeedSourceConfig
    variables: dict[VariableName, NonemptyString] = Field(default_factory=dict)
    providers: dict[Identifier, ProviderConfig]
    model: ModelConfig
    agents: dict[Identifier, AgentConfig]
    environment: EnvironmentConfig
    runtime: RuntimeConfig
    verifier: VerifierConfig | None = None
    tools: dict[Identifier, ToolConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if sum(agent.target for agent in self.agents.values()) != 1:
            raise ValueError("agents must contain exactly one explicit Target Agent")
        if self.environment.type == "single" and len(self.agents) != 1:
            raise ValueError("environment.single requires exactly one Agent")
        if self.environment.type == "dialogue" and set(self.agents) != {
            "user",
            "assistant",
        }:
            raise ValueError("environment.dialogue requires user and assistant Agents")
        if (
            self.seed.id_variable is not None
            and self.seed.id_variable not in self.variables
        ):
            raise ValueError("seed.id_variable must name a declared Variable alias")
        for kind, names in (
            ("agents", self.agents),
            ("providers", self.providers),
            ("tools", self.tools),
        ):
            unique_names(list(names), f"{kind} identifiers")
        for agent_id, agent in self.agents.items():
            if len(set(agent.tools)) != len(agent.tools):
                raise ValueError(f"agents.{agent_id}.tools assignments must be unique")
            undeclared = set(agent.tools) - self.tools.keys()
            if undeclared:
                raise ValueError(
                    f"agents.{agent_id}.tools reference an undeclared Tool: "
                    + ", ".join(sorted(undeclared))
                )
        if {name.casefold() for name in self.tools}.intersection(CONTROL_TOOLS):
            raise ValueError(
                "Tool identifiers collide with reserved Task Step controls"
            )
        references = [self.model.provider] + [
            agent.model.provider
            for agent in self.agents.values()
            if agent.model.provider is not None
        ]
        references += [
            agent.reviewer.model.provider
            for agent in self.agents.values()
            if agent.reviewer is not None and agent.reviewer.model.provider is not None
        ]
        if self.verifier is not None and self.verifier.model.provider is not None:
            references.append(self.verifier.model.provider)
        for reference in references:
            if reference not in self.providers:
                raise ValueError(
                    f"model.provider references undeclared Provider {reference!r}"
                )
        return self
