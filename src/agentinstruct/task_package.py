"""Load Task Packages and compile one JSON Seed without constructing components."""

import json
import math
import platform
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import Self, cast

from jinja2 import StrictUndefined, TemplateError, Undefined, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment
from pydantic import ValidationError

from agentinstruct.plans import (
    AgentPlan,
    EnvironmentPlan,
    FrozenJsonValue,
    JsonValue,
    ModelPlan,
    PlanProvenance,
    ProviderPlan,
    RunPlan,
    RuntimePlan,
    Seed,
    SeedOrigin,
    TaskIdentity,
    content_digest,
    freeze,
)
from agentinstruct.task_config import PackageConfig


class TaskValidationError(ValueError):
    """Invalid authoring input, reported without echoing configuration values."""


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise TaskValidationError(f"{label}: cannot read UTF-8 file") from exc


def _package_path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise TaskValidationError(f"{relative}: expected a package-relative path")
    try:
        resolved = (root / path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TaskValidationError(
            f"{relative}: missing or unsafe package file"
        ) from exc
    if not resolved.is_relative_to(root):
        raise TaskValidationError(f"{relative}: path escapes the Task Package")
    return resolved


def _external_path(path: str | Path) -> Path:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise TaskValidationError(f"{path}: cannot resolve input path") from exc


def _template_value(value: object) -> object:
    # Never turn a bound method or other runtime object into an address-bearing
    # instruction string. Undefined must reach Jinja's strict error handling.
    if not isinstance(value, Undefined):
        json.dumps(value, allow_nan=False)
    return value


class _InstructionEnvironment(ImmutableSandboxedEnvironment):
    def is_safe_attribute(self, obj: object, attr: str, value: object) -> bool:
        # Block runtime attributes before filters/concatenation can stringify them.
        try:
            _template_value(value)
        except (TypeError, ValueError):
            return False
        return super().is_safe_attribute(obj, attr, value)


def _data_filter(function: Callable[..., object]) -> Callable[..., object]:
    @wraps(function)
    def apply(*args: object, **kwargs: object) -> object:
        value = function(*args, **kwargs)
        # map/select/items return iterators; materialize them before a subsequent
        # filter or '~' can render a generator's nondeterministic representation.
        if isinstance(value, Iterator):
            value = list(value)
        return _template_value(value)

    return apply


def _template_environment() -> ImmutableSandboxedEnvironment:
    env = _InstructionEnvironment(
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        finalize=_template_value,
    )
    # Task templates receive only declared Variables and Jinja's filters/tests.
    env.globals.clear()
    env.filters.pop("random")
    env.filters = {name: _data_filter(fn) for name, fn in env.filters.items()}
    return env


def _json_object(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite numbers are not valid JSON Seed data")
    return result


@dataclass(frozen=True)
class AgentSource:
    id: str
    target: bool
    model: ModelPlan
    instruction: str
    type: str
    responses: tuple[str, ...]


@dataclass(frozen=True)
class SeedSource:
    path: str
    id_variable: str | None


@dataclass(frozen=True)
class TaskPackage:
    root: Path
    schema_version: str
    task: TaskIdentity
    seed_source: SeedSource
    variables: Mapping[str, str]
    providers: Mapping[str, ProviderPlan]
    agents: Mapping[str, AgentSource]
    environment: EnvironmentPlan
    runtime: RuntimePlan
    source_files: Mapping[str, str]

    @classmethod
    def load(cls, path: str | Path) -> Self:
        """Validate static input and snapshot unresolved instruction templates."""
        root = _external_path(path)
        raw = _read_text(_package_path(root, "task.toml"), "task.toml")
        try:
            config = PackageConfig.model_validate(tomllib.loads(raw))
        except tomllib.TOMLDecodeError as exc:
            raise TaskValidationError(f"task.toml: malformed TOML: {exc}") from exc
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'package'}: "
                f"{error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise TaskValidationError(f"task.toml: {problems}") from exc

        sources: dict[str, AgentSource] = {}
        source_files = {"task.toml": raw}
        env = _template_environment()
        for agent_id, agent in config.agents.items():
            label = f"agents/{agent_id}/instruction.md"
            instruction = _read_text(_package_path(root, label), label)
            source_files[label] = instruction
            try:
                unknown = meta.find_undeclared_variables(env.parse(instruction)) - set(
                    config.variables
                )
                if unknown:
                    raise TaskValidationError(
                        f"{label}: undeclared Variables: {', '.join(sorted(unknown))}"
                    )
            except TemplateError as exc:
                raise TaskValidationError(f"{label}: invalid template: {exc}") from exc
            override = agent.model
            model = ModelPlan(
                provider=override.provider or config.model.provider,
                name=override.name or config.model.name,
                temperature=(
                    override.temperature
                    if override.temperature is not None
                    else config.model.temperature
                ),
                max_tokens=(
                    override.max_tokens
                    if override.max_tokens is not None
                    else config.model.max_tokens
                ),
            )
            sources[agent_id] = AgentSource(
                agent_id,
                agent.target,
                model,
                instruction,
                agent.type,
                tuple(agent.responses),
            )

        package_digest = content_digest(
            {"config": config.model_dump(mode="json"), "agents": sources}
        )
        providers = {
            provider_id: ProviderPlan(
                id=provider_id,
                type=provider.type,
                api=provider.api
                or ("responses" if provider.type == "openai" else "chat_completions"),
                base_url=provider.base_url,
                api_key_env=provider.api_key_env,
            )
            for provider_id, provider in config.providers.items()
        }
        return cls(
            root=root,
            schema_version=config.schema_version,
            task=TaskIdentity(config.task.id, config.task.version, package_digest),
            seed_source=SeedSource(config.seed.path, config.seed.id_variable),
            variables=MappingProxyType(dict(config.variables)),
            providers=MappingProxyType(providers),
            agents=MappingProxyType(sources),
            environment=EnvironmentPlan(
                config.environment.type, config.environment.max_turns
            ),
            runtime=RuntimePlan(config.runtime.type),
            source_files=MappingProxyType(source_files),
        )

    def compile(self, *, seed_path: str | Path | None = None) -> RunPlan:
        """Bind one JSON object Seed to this package's frozen authoring snapshot."""
        if seed_path is None:
            path = _package_path(self.root, self.seed_source.path)
            origin = self.seed_source.path
        else:
            path = _external_path(seed_path)
            origin = str(path)
        raw = _read_text(path, origin)
        try:
            data = json.loads(
                raw,
                object_pairs_hook=_json_object,
                parse_float=_json_float,
                parse_constant=_json_float,
            )
        except json.JSONDecodeError as exc:
            raise TaskValidationError(
                f"{origin}: malformed JSON at line {exc.lineno}, column {exc.colno}"
            ) from exc
        except ValueError as exc:
            raise TaskValidationError(f"{origin}: {exc}") from exc
        if not isinstance(data, dict):
            raise TaskValidationError(f"{origin}: expected one JSON object Seed")
        seed_data = cast(dict[str, JsonValue], data)
        extracted: dict[str, JsonValue] = {}
        for alias, selector in self.variables.items():
            value: JsonValue = seed_data
            for segment in selector.split("."):
                if not isinstance(value, dict) or segment not in value:
                    raise TaskValidationError(
                        f"{origin}: Variable {alias!r} selector "
                        f"{selector!r} does not resolve"
                    )
                value = value[segment]
            extracted[alias] = value
        seed_digest = content_digest(seed_data)
        seed_id = seed_digest
        if self.seed_source.id_variable is not None:
            id_value = extracted[self.seed_source.id_variable]
            if (
                isinstance(id_value, bool)
                or not isinstance(id_value, (str, int))
                or not str(id_value).strip()
            ):
                raise TaskValidationError(
                    f"{origin}: seed.id_variable must resolve to a "
                    "nonempty string or integer"
                )
            seed_id = str(id_value)

        env = _template_environment()
        agents: dict[str, AgentPlan] = {}
        for agent_id, source in self.agents.items():
            try:
                instruction = env.from_string(source.instruction).render(extracted)
            except (TemplateError, TypeError, ValueError, ArithmeticError) as exc:
                raise TaskValidationError(
                    f"agents/{agent_id}/instruction.md: rendering failed "
                    f"({type(exc).__name__}): {exc}"
                ) from exc
            agents[agent_id] = AgentPlan(
                agent_id,
                source.target,
                source.model,
                instruction,
                source.type,
                source.responses,
            )

        frozen_data = cast(Mapping[str, FrozenJsonValue], freeze(seed_data))
        frozen_variables = cast(Mapping[str, FrozenJsonValue], freeze(extracted))
        return RunPlan(
            schema_version=self.schema_version,
            task=self.task,
            seed=Seed(seed_id, frozen_data, SeedOrigin(origin), seed_digest),
            variables=frozen_variables,
            providers=self.providers,
            agents=MappingProxyType(agents),
            environment=self.environment,
            runtime=self.runtime,
            provenance=PlanProvenance(
                version("agentinstruct"), platform.python_version()
            ),
        )
