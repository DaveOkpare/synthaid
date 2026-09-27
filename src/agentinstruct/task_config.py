"""Strict authoring schema for built-in generation Task Packages."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentinstruct.quality import Criterion, Rubric

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")]
VariableName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
Selector = Annotated[str, Field(pattern=r"^[^.\[\]\s]+(?:\.[^.\[\]\s]+)*$")]
NonemptyString = Annotated[str, Field(min_length=1)]


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TaskConfig(ConfigModel):
    id: Identifier
    version: NonemptyString


class SeedSourceConfig(ConfigModel):
    path: NonemptyString
    id_variable: VariableName | None = None


class ProviderConfig(ConfigModel):
    type: Literal["openai", "openai-compatible", "vllm"]
    api: Literal["responses", "chat_completions"] | None = None
    base_url: str | None = None
    api_key_env: VariableName | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                url = urlsplit(value)
                valid = (
                    url.scheme in {"http", "https"}
                    and url.hostname
                    and not url.username
                    and not url.password
                    and not url.query
                    and not url.fragment
                )
                _ = url.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(
                    "expected an HTTP(S) URL without credentials, query, or fragment"
                )
        return value


class ModelConfig(ConfigModel):
    provider: Identifier
    name: NonemptyString
    temperature: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(gt=0)] | None = None


class ModelOverride(ConfigModel):
    provider: Identifier | None = None
    name: NonemptyString | None = None
    temperature: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(gt=0)] | None = None


class ScriptedResponseConfig(ConfigModel):
    content: str
    control: Literal["complete"] | None = None


class ReviewerConfig(ConfigModel):
    type: Literal["custom", "deterministic"]
    max_revisions: Annotated[int, Field(ge=0)] = 1
    accept_on_revision_exhaustion: bool = False
    checks: dict[Identifier, Literal["nonempty_content"]] = Field(default_factory=dict)


class AgentConfig(ConfigModel):
    target: bool
    model: ModelOverride = Field(default_factory=ModelOverride)
    type: Literal["model", "scripted"] = "model"
    responses: list[str | ScriptedResponseConfig] = Field(default_factory=list)
    reviewer: ReviewerConfig | None = None

    @model_validator(mode="after")
    def validate_script(self) -> Self:
        if self.type == "scripted" and not self.responses:
            raise ValueError("scripted Agents require at least one response")
        if self.type != "scripted" and self.responses:
            raise ValueError("responses require a scripted Agent")
        return self


class EnvironmentConfig(ConfigModel):
    type: Literal["single", "dialogue"]
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


class VerifierConfig(ConfigModel):
    type: Literal["custom", "deterministic"]
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 60.0
    checks: dict[
        Identifier, Literal["nonempty_conversation", "generation_terminated"]
    ] = Field(default_factory=dict)


class PackageConfig(ConfigModel):
    schema_version: Literal["1"]
    task: TaskConfig
    seed: SeedSourceConfig
    variables: dict[VariableName, Selector] = Field(default_factory=dict)
    providers: dict[Identifier, ProviderConfig]
    model: ModelConfig
    agents: dict[Identifier, AgentConfig]
    environment: EnvironmentConfig
    runtime: RuntimeConfig
    verifier: VerifierConfig | None = None

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
        for kind, names in (("agents", self.agents), ("providers", self.providers)):
            if len({name.casefold() for name in names}) != len(names):
                raise ValueError(f"{kind} identifiers collide after case normalization")
        references = [self.model.provider] + [
            agent.model.provider
            for agent in self.agents.values()
            if agent.model.provider is not None
        ]
        for reference in references:
            if reference not in self.providers:
                raise ValueError(
                    f"model.provider references undeclared Provider {reference!r}"
                )
        return self
