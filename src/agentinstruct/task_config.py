"""Strict authoring schema for the initial single-Agent Task Package slice."""

from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class AgentConfig(ConfigModel):
    target: bool
    model: ModelOverride = Field(default_factory=ModelOverride)


class EnvironmentConfig(ConfigModel):
    type: Literal["single"]
    max_turns: Annotated[int, Field(gt=0)] = 1


class RuntimeConfig(ConfigModel):
    type: Literal["local"]


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

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if sum(agent.target for agent in self.agents.values()) != 1:
            raise ValueError("agents must contain exactly one explicit Target Agent")
        if len(self.agents) != 1:
            raise ValueError("environment.single requires exactly one Agent")
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
