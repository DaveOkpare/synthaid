"""Load Task Packages and compile Seed records without constructing components."""

import json
import platform
import tomllib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
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
    JsonSchema,
    JsonValue,
    ModelPlan,
    PlanProvenance,
    ProviderPlan,
    ReviewerPlan,
    RunPlan,
    RuntimePlan,
    ScriptedResponse,
    Seed,
    StepAgentPlan,
    StepPlan,
    TaskIdentity,
    ToolPlan,
    VerifierPlan,
    content_digest,
    freeze,
    json_value,
)
from agentinstruct.quality import Criterion, Rubric
from agentinstruct.seeds import SeedRecord, SeedSourceError, read_seed_records
from agentinstruct.task_config import PackageConfig, RubricConfig, StepRubricConfig
from agentinstruct.tools import schema_validator


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


def _load_rubric(root: Path, label: str, *, step: bool = False) -> tuple[Rubric, str]:
    """Load weighted Criteria and source text with input-scrubbed diagnostics."""
    text = _read_text(_package_path(root, label), label)
    try:
        data = tomllib.loads(text)
        rubric = (
            Rubric(StepRubricConfig.model_validate(data).to_criteria())
            if step
            else RubricConfig.model_validate(data).to_rubric()
        )
    except tomllib.TOMLDecodeError as exc:
        raise TaskValidationError(f"{label}: malformed TOML: {exc}") from exc
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'rubric'}: "
            f"{error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise TaskValidationError(f"{label}: invalid Rubric: {problems}") from exc
    return rubric, text


def _external_path(path: str | Path) -> Path:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise TaskValidationError(f"{path}: cannot resolve input path") from exc


def _directory_members(root: Path, label: str, expected: set[str]) -> None:
    path = _package_path(root, label)
    try:
        actual = {child.name for child in path.iterdir()}
    except OSError as exc:
        raise TaskValidationError(f"{label}: expected a readable directory") from exc
    if actual != expected:
        raise TaskValidationError(
            f"{label}: directories must match declared participation"
        )


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


def _load_template(
    root: Path,
    label: str,
    env: ImmutableSandboxedEnvironment,
    variables: Mapping[str, str],
) -> str:
    instruction = _read_text(_package_path(root, label), label)
    try:
        unknown = meta.find_undeclared_variables(env.parse(instruction)) - set(
            variables
        )
        if unknown:
            raise TaskValidationError(
                f"{label}: undeclared Variables: {', '.join(sorted(unknown))}"
            )
    except TemplateError as exc:
        raise TaskValidationError(f"{label}: invalid template: {exc}") from exc
    return instruction


def _render_template(
    instruction: str,
    label: str,
    env: ImmutableSandboxedEnvironment,
    variables: Mapping[str, JsonValue],
) -> str:
    try:
        return env.from_string(instruction).render(variables)
    except (TemplateError, TypeError, ValueError, ArithmeticError) as exc:
        raise TaskValidationError(
            f"{label}: rendering failed ({type(exc).__name__}): {exc}"
        ) from exc


@dataclass(frozen=True)
class AgentSource:
    id: str
    target: bool
    model: ModelPlan
    instruction: str
    type: str
    responses: tuple[str | ScriptedResponse, ...]
    reviewer: ReviewerPlan | None = None
    rubric: Rubric | None = None
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeedSource:
    path: str
    id_variable: str | None


@dataclass(frozen=True)
class StepSource:
    """Unresolved step additions, compiled for every Seed before execution."""

    id: str
    agents: Mapping[str, StepAgentPlan]

    def __post_init__(self) -> None:
        object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))


@dataclass(frozen=True)
class SeedCompilation:
    record: SeedRecord
    seed_id: str
    plan: RunPlan | None
    error: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    records: tuple[SeedCompilation, ...]
    source_error: str | None = None

    @property
    def valid(self) -> bool:
        return self.source_error is None and all(
            item.plan is not None for item in self.records
        )

    def to_dict(self) -> dict[str, object]:
        plans = [item.plan.to_dict() for item in self.records if item.plan is not None]
        errors = [item.error for item in self.records if item.error is not None]
        result: dict[str, object] = {
            "status": "valid" if self.valid else "invalid",
            "counts": {"valid": len(plans), "invalid": len(errors)},
            "plans": plans,
            "records": [
                {
                    "seed_id": item.seed_id,
                    "origin": json_value(item.record.origin),
                    "status": "valid" if item.plan is not None else "invalid",
                    "error": item.error,
                }
                for item in self.records
            ],
            "source_error": self.source_error,
        }
        if not self.valid:
            result["error"] = self.source_error or errors[0]
        if self.valid and len(plans) == 1:
            result["plan"] = plans[0]
        return result


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
    verifier: VerifierPlan | None = None
    tools: Mapping[str, ToolPlan] = field(default_factory=dict)
    steps: tuple[StepSource, ...] = ()

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
            instruction = _load_template(root, label, env, config.variables)
            source_files[label] = instruction
            reviewer = None
            rubric = None
            if agent.reviewer is not None:
                label = f"agents/{agent_id}/reviewer.md"
                reviewer_instruction = _load_template(
                    root, label, env, config.variables
                )
                source_files[label] = reviewer_instruction
                label = f"agents/{agent_id}/rubric.toml"
                rubric, rubric_text = _load_rubric(root, label)
                source_files[label] = rubric_text
                try:
                    reviewer = ReviewerPlan(
                        agent.reviewer.type,
                        reviewer_instruction,
                        agent.reviewer.max_revisions,
                        agent.reviewer.accept_on_revision_exhaustion,
                        agent.reviewer.checks,
                    )
                except ValueError as exc:
                    raise TaskValidationError(
                        f"agents/{agent_id}/reviewer: {exc}"
                    ) from exc
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
                tuple(
                    response
                    if isinstance(response, str)
                    else ScriptedResponse(response.content, response.control)
                    for response in agent.responses
                ),
                reviewer,
                rubric,
                tuple(agent.tools),
            )

        steps: list[StepSource] = []
        if config.task.steps:
            _directory_members(root, "steps", set(config.task.steps))
        elif (root / "steps").exists() or (root / "steps").is_symlink():
            raise TaskValidationError("steps: directory requires declared Task Steps")
        for step_id in config.task.steps:
            _directory_members(root, f"steps/{step_id}", {"agents"})
            _directory_members(root, f"steps/{step_id}/agents", set(sources))
            additions: dict[str, StepAgentPlan] = {}
            for agent_id in sources:
                label = f"steps/{step_id}/agents/{agent_id}/instruction.md"
                instruction = _load_template(root, label, env, config.variables)
                source_files[label] = instruction
                rubric_label = f"steps/{step_id}/agents/{agent_id}/rubric.toml"
                appended: tuple[Criterion, ...] = ()
                if (root / rubric_label).exists() or (root / rubric_label).is_symlink():
                    if sources[agent_id].rubric is None:
                        raise TaskValidationError(
                            f"{rubric_label}: step Criteria require an Agent Reviewer"
                        )
                    step_rubric, text = _load_rubric(root, rubric_label, step=True)
                    source_files[rubric_label] = text
                    appended = step_rubric.criteria
                    base = sources[agent_id].rubric
                    assert base is not None
                    try:
                        Rubric(base.criteria + appended, base.threshold)
                    except ValueError as exc:
                        raise TaskValidationError(f"{rubric_label}: {exc}") from exc
                additions[agent_id] = StepAgentPlan(instruction, appended)
            steps.append(StepSource(step_id, MappingProxyType(additions)))

        for agent_id, source in sources.items():
            if source.reviewer is not None and source.reviewer.type == "deterministic":
                assert source.rubric is not None
                criteria = {criterion.id for criterion in source.rubric.criteria}
                criteria.update(
                    criterion.id
                    for step in steps
                    for criterion in step.agents[agent_id].appended_rubric
                )
                if set(source.reviewer.checks) != criteria:
                    raise TaskValidationError(
                        f"agents/{agent_id}/reviewer: Deterministic checks must "
                        "match every Criterion ID"
                    )

        verifier = None
        if config.verifier is not None:
            label = "verifier/rubric.toml"
            verifier_rubric, rubric_text = _load_rubric(root, label)
            source_files[label] = rubric_text
            try:
                verifier = VerifierPlan(
                    config.verifier.type,
                    verifier_rubric,
                    config.verifier.timeout_seconds,
                    config.verifier.checks,
                )
            except ValueError as exc:
                raise TaskValidationError(f"verifier: {exc}") from exc

        tools = {
            tool_id: ToolPlan(
                tool_id,
                tool.description,
                cast(JsonSchema, freeze(tool.input_schema)),
                cast(JsonSchema | None, freeze(tool.output_schema)),
                tool.execution_errors,
            )
            for tool_id, tool in config.tools.items()
        }
        for tool_id, tool in tools.items():
            try:
                schema_validator(tool.input_schema)
                if tool.output_schema is not None:
                    schema_validator(tool.output_schema)
            except Exception as exc:
                raise TaskValidationError(
                    f"tools/{tool_id}: invalid JSON Schema"
                ) from exc
        package_digest = content_digest(
            {
                "config": config.model_dump(mode="json"),
                "agents": sources,
                "steps": steps,
                "verifier": verifier,
            }
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
                config.environment.type,
                config.environment.max_turns,
                config.environment.initiator,
                config.environment.max_rounds,
                config.environment.timeout_seconds,
            ),
            runtime=RuntimePlan(config.runtime.type),
            source_files=MappingProxyType(source_files),
            verifier=verifier,
            tools=MappingProxyType(tools),
            steps=tuple(steps),
        )

    def seed_records(
        self, *, seed_path: str | Path | None = None
    ) -> Iterator[SeedRecord]:
        """Enumerate source records without constructing runtime components."""
        try:
            if seed_path is None:
                path = _package_path(self.root, self.seed_source.path)
                origin = self.seed_source.path
            else:
                path = _external_path(seed_path)
                origin = str(path)
        except TaskValidationError as exc:
            raise SeedSourceError(str(exc)) from exc
        yield from read_seed_records(path, origin)

    def compile(self, *, seed_path: str | Path | None = None) -> RunPlan:
        """Compile exactly one record; use Runner or validate for collections."""
        try:
            records = self.seed_records(seed_path=seed_path)
            record = next(records, None)
            if record is None or next(records, None) is not None:
                raise TaskValidationError("compile requires exactly one Seed record")
            return self.compile_seed(self.bind_seed(record))
        except SeedSourceError as exc:
            raise TaskValidationError(str(exc)) from exc

    def compile_records(
        self, *, seed_path: str | Path | None = None
    ) -> Iterator[SeedCompilation]:
        """Compile independently and enforce Run-wide identity without live state."""
        seen: set[str] = set()
        for record in self.seed_records(seed_path=seed_path):
            seed_id = record.digest
            try:
                seed = self.bind_seed(record)
                seed_id = seed.id
                if seed_id in seen:
                    raise TaskValidationError(
                        f"{record.origin.path}: record {record.origin.record}: "
                        f"duplicate Seed ID {seed_id!r}"
                    )
                seen.add(seed_id)
                plan = self.compile_seed(seed)
            except TaskValidationError as exc:
                yield SeedCompilation(record, seed_id, None, str(exc))
            else:
                yield SeedCompilation(record, seed_id, plan)

    def validate(self, *, seed_path: str | Path | None = None) -> ValidationResult:
        """Validate every selected record without creating Run storage or components."""
        records: list[SeedCompilation] = []
        source_error = None
        try:
            records.extend(self.compile_records(seed_path=seed_path))
        except SeedSourceError as exc:
            source_error = str(exc)
        return ValidationResult(tuple(records), source_error)

    def _variable(
        self, alias: str, data: Mapping[str, FrozenJsonValue]
    ) -> FrozenJsonValue:
        selector = self.variables[alias]
        value: FrozenJsonValue = data
        for segment in selector.split("."):
            if not isinstance(value, Mapping) or segment not in value:
                raise TaskValidationError(
                    f"Variable {alias!r} selector {selector!r} does not resolve"
                )
            value = value[segment]
        return value

    def bind_seed(self, record: SeedRecord) -> Seed:
        """Assign stable logical identity before rendering any executable Plan."""
        label = f"{record.origin.path}: record {record.origin.record}"
        if record.error is not None:
            raise TaskValidationError(record.error)
        if not isinstance(record.data, Mapping):
            raise TaskValidationError(f"{label}: expected a JSON object Seed")
        seed_id = record.digest
        if self.seed_source.id_variable is not None:
            try:
                value = self._variable(self.seed_source.id_variable, record.data)
            except TaskValidationError as exc:
                raise TaskValidationError(f"{label}: {exc}") from exc
            if (
                isinstance(value, bool)
                or not isinstance(value, (str, int))
                or not str(value).strip()
            ):
                raise TaskValidationError(
                    f"{label}: seed.id_variable must resolve to a "
                    "nonempty string or integer"
                )
            seed_id = str(value)
        return Seed(seed_id, record.data, record.origin, record.digest)

    def compile_seed(self, seed: Seed) -> RunPlan:
        """Compile one bound Seed into an independent immutable execution input."""
        extracted: dict[str, JsonValue] = {}
        for alias in self.variables:
            try:
                extracted[alias] = json_value(self._variable(alias, seed.data))
            except TaskValidationError as exc:
                raise TaskValidationError(
                    f"{seed.origin.path}: record {seed.origin.record}: {exc}"
                ) from exc

        env = _template_environment()
        agents: dict[str, AgentPlan] = {}
        for agent_id, source in self.agents.items():
            instruction = _render_template(
                source.instruction, f"agents/{agent_id}/instruction.md", env, extracted
            )
            reviewer = source.reviewer
            if reviewer is not None:
                reviewer = replace(
                    reviewer,
                    instruction=_render_template(
                        reviewer.instruction,
                        f"agents/{agent_id}/reviewer.md",
                        env,
                        extracted,
                    ),
                )
            agents[agent_id] = AgentPlan(
                agent_id,
                source.target,
                source.model,
                instruction,
                source.type,
                source.responses,
                reviewer,
                source.rubric,
                source.tools,
            )

        steps: list[StepPlan] = []
        for step in self.steps:
            additions: dict[str, StepAgentPlan] = {}
            for agent_id, addition in step.agents.items():
                instruction = _render_template(
                    addition.instruction,
                    f"steps/{step.id}/agents/{agent_id}/instruction.md",
                    env,
                    extracted,
                )
                additions[agent_id] = replace(addition, instruction=instruction)
            steps.append(StepPlan(step.id, additions))

        frozen_variables = cast(Mapping[str, FrozenJsonValue], freeze(extracted))
        return RunPlan(
            schema_version=self.schema_version,
            task=self.task,
            seed=seed,
            variables=frozen_variables,
            providers=self.providers,
            agents=MappingProxyType(agents),
            environment=self.environment,
            runtime=self.runtime,
            provenance=PlanProvenance(
                version("agentinstruct"), platform.python_version()
            ),
            verifier=self.verifier,
            tools=self.tools,
            steps=tuple(steps),
        )
