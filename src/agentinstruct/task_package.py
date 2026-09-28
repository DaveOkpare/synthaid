"""Load Task Packages and compile Seed records without constructing components."""

import json
import platform
import re
import tomllib
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from functools import wraps
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import Self, cast

from jinja2 import StrictUndefined, TemplateError, Undefined, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError
from referencing import Resource
from referencing.jsonschema import DRAFT202012

from agentinstruct.paths import package_path, relative_path
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
from agentinstruct.quality_provider import QualityDecision
from agentinstruct.seeds import (
    SeedInput,
    SeedRecord,
    SeedSourceError,
    parse_json,
    read_python_records,
    read_seed_records,
    seed_files,
)
from agentinstruct.structured import compile_structured_output
from agentinstruct.task_config import (
    ModelConfig,
    ModelOverride,
    PackageConfig,
    RubricConfig,
    StepRubricConfig,
)
from agentinstruct.tools import schema_validator


def _model_plan(base: ModelPlan | ModelConfig, override: ModelOverride) -> ModelPlan:
    return ModelPlan(
        override.provider or base.provider,
        override.name or base.name,
        override.temperature if override.temperature is not None else base.temperature,
        override.max_tokens if override.max_tokens is not None else base.max_tokens,
    )


class TaskValidationError(ValueError):
    """Invalid authoring input, reported without echoing configuration values."""


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as exc:
        raise TaskValidationError(f"{label}: cannot read UTF-8 file") from exc


def _package_path(root: Path, relative: str) -> Path:
    try:
        return package_path(root, relative)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TaskValidationError(
            f"{relative}: missing or unsafe package file: {exc}"
        ) from exc


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


def _directory_members(
    root: Path,
    label: str,
    expected: set[str],
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    path = _package_path(root, label)
    try:
        actual = {child.name for child in path.iterdir()}
    except OSError as exc:
        raise TaskValidationError(f"{label}: expected a readable directory") from exc
    missing = expected - actual
    undeclared = actual - expected - optional
    if missing or undeclared:
        details = []
        if missing:
            details.append(
                "missing " + ", ".join(f"{label}/{name}" for name in sorted(missing))
            )
        if undeclared:
            details.append(
                "undeclared "
                + ", ".join(f"{label}/{name}" for name in sorted(undeclared))
            )
        raise TaskValidationError(
            f"{label}: directories must match declared participation: "
            + "; ".join(details)
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
    schema: JsonSchema | None = None
    glob: str | None = None


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
        try:
            seed_path = relative_path(config.seed.path).as_posix()
        except ValueError as exc:
            raise TaskValidationError(f"seed.path: {exc}") from exc

        sources: dict[str, AgentSource] = {}
        source_files = {"task.toml": raw}
        seed_schema = None
        if config.seed.schema_path is not None:
            label = config.seed.schema_path
            text = _read_text(_package_path(root, label), label)
            try:
                data = parse_json(text, label)
                if not isinstance(data, (dict, bool)):
                    raise ValueError("expected a JSON Schema object or Boolean")
                seed_schema = cast(JsonSchema, freeze(data))
                schema_validator(seed_schema)
                _require_local_schema_references(data)
            except Exception as exc:
                raise TaskValidationError(
                    f"{label}: invalid Seed schema; requires a valid JSON Schema "
                    "with local references only"
                ) from exc
            source_files[label] = text
        env = _template_environment()
        _directory_members(root, "agents", set(config.agents))
        for agent_id, agent in config.agents.items():
            required = {"instruction.md"}
            if agent.reviewer is not None:
                required.update({"reviewer.md", "rubric.toml"})
            _directory_members(root, f"agents/{agent_id}", required)
            label = f"agents/{agent_id}/instruction.md"
            instruction = _load_template(root, label, env, config.variables)
            source_files[label] = instruction
            model = _model_plan(config.model, agent.model)
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
                        _model_plan(model, agent.reviewer.model)
                        if agent.reviewer.type == "model"
                        else None,
                        compile_structured_output(QualityDecision)
                        if agent.reviewer.type == "model"
                        else None,
                    )
                except ValueError as exc:
                    raise TaskValidationError(
                        f"agents/{agent_id}/reviewer: {exc}"
                    ) from exc
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
                _directory_members(
                    root,
                    f"steps/{step_id}/agents/{agent_id}",
                    {"instruction.md"},
                    optional=frozenset({"rubric.toml"}),
                )
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
            verifier_files = {"rubric.toml"}
            verifier_instruction = (
                "Evaluate the completed Trace against every declared Criterion."
            )
            if config.verifier.type == "model":
                verifier_files.add("instruction.md")
                label = "verifier/instruction.md"
                verifier_instruction = _load_template(
                    root, label, env, config.variables
                )
                source_files[label] = verifier_instruction
            _directory_members(root, "verifier", verifier_files)
            label = "verifier/rubric.toml"
            verifier_rubric, rubric_text = _load_rubric(root, label)
            source_files[label] = rubric_text
            try:
                verifier = VerifierPlan(
                    config.verifier.type,
                    verifier_rubric,
                    config.verifier.timeout_seconds,
                    config.verifier.checks,
                    _model_plan(config.model, config.verifier.model)
                    if config.verifier.type == "model"
                    else None,
                    compile_structured_output(QualityDecision)
                    if config.verifier.type == "model"
                    else None,
                    verifier_instruction,
                )
            except ValueError as exc:
                raise TaskValidationError(f"verifier: {exc}") from exc
        elif (root / "verifier").exists() or (root / "verifier").is_symlink():
            raise TaskValidationError(
                "verifier: directory requires a declared Verifier"
            )

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
                "seed_schema": seed_schema,
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
            seed_source=SeedSource(
                seed_path, config.seed.id_variable, seed_schema, config.seed.glob
            ),
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
        self,
        *,
        seed_path: str | Path | None = None,
        seeds: Iterable[SeedInput] | None = None,
    ) -> Iterator[SeedRecord]:
        """Enumerate source records without constructing runtime components."""
        if seeds is not None:
            if seed_path is not None:
                raise SeedSourceError("seeds and seed_path are mutually exclusive")
            yield from read_python_records(seeds)
            return
        try:
            if seed_path is None:
                path = _package_path(self.root, self.seed_source.path)
                origin = self.seed_source.path
            else:
                path = _external_path(seed_path)
                origin = str(path)
        except TaskValidationError as exc:
            raise SeedSourceError(str(exc)) from exc
        for source, label in seed_files(path, origin, self.seed_source.glob):
            yield from read_seed_records(source, label)

    def compile(
        self,
        *,
        seed_path: str | Path | None = None,
        seeds: Iterable[SeedInput] | None = None,
    ) -> RunPlan:
        """Compile exactly one record; use Runner or validate for collections."""
        try:
            records = self.seed_records(seed_path=seed_path, seeds=seeds)
            record = next(records, None)
            if record is None or next(records, None) is not None:
                raise TaskValidationError("compile requires exactly one Seed record")
            return self.compile_seed(self.bind_seed(record))
        except SeedSourceError as exc:
            raise TaskValidationError(str(exc)) from exc

    def compile_records(
        self,
        *,
        seed_path: str | Path | None = None,
        seeds: Iterable[SeedInput] | None = None,
    ) -> Iterator[SeedCompilation]:
        """Compile independently and enforce Run-wide identity without live state."""
        seen: set[str] = set()
        for record in self.seed_records(seed_path=seed_path, seeds=seeds):
            seed_id = record.seed_id or record.digest
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

    def validate(
        self,
        *,
        seed_path: str | Path | None = None,
        seeds: Iterable[SeedInput] | None = None,
    ) -> ValidationResult:
        """Validate every selected record without creating Run storage or components."""
        records: list[SeedCompilation] = []
        source_error = None
        try:
            records.extend(self.compile_records(seed_path=seed_path, seeds=seeds))
        except SeedSourceError as exc:
            source_error = str(exc)
        return ValidationResult(tuple(records), source_error)

    def _variable(
        self, alias: str, data: Mapping[str, FrozenJsonValue], *, flat: bool = False
    ) -> FrozenJsonValue:
        selector = self.variables[alias]
        if not flat and not re.fullmatch(r"[^.\[\]\s]+(?:\.[^.\[\]\s]+)*", selector):
            raise TaskValidationError(
                f"Variable {alias!r} selector {selector!r} "
                "must be a valid JSON dot path"
            )
        value: FrozenJsonValue = data
        for segment in [selector] if flat else selector.split("."):
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
        self._validate_seed_schema(record.data, label)
        seed_id = record.seed_id or record.digest
        if record.seed_id is None and self.seed_source.id_variable is not None:
            try:
                value = self._variable(
                    self.seed_source.id_variable,
                    record.data,
                    flat=record.origin.format == "csv",
                )
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
        record = next(read_python_records([seed]))
        if record.error is not None:
            raise TaskValidationError(record.error)
        if not isinstance(record.data, Mapping):
            raise TaskValidationError("compile_seed requires a JSON object Seed")
        seed = replace(seed, data=record.data, digest=record.digest)
        self._validate_seed_schema(
            seed.data, f"{seed.origin.path}: record {seed.origin.record}"
        )
        extracted: dict[str, JsonValue] = {}
        for alias in self.variables:
            try:
                extracted[alias] = json_value(
                    self._variable(alias, seed.data, flat=seed.origin.format == "csv")
                )
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
        verifier = self.verifier
        if verifier is not None and verifier.type == "model":
            verifier = replace(
                verifier,
                instruction=_render_template(
                    verifier.instruction,
                    "verifier/instruction.md",
                    env,
                    extracted,
                ),
            )
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
            verifier=verifier,
            tools=self.tools,
            steps=tuple(steps),
        )

    def _validate_seed_schema(
        self, data: Mapping[str, FrozenJsonValue], label: str
    ) -> None:
        if self.seed_source.schema is None:
            return
        try:
            schema_validator(self.seed_source.schema).validate(json_value(data))
        except SchemaValidationError as exc:
            path = "/" + "/".join(str(part) for part in exc.absolute_path)
            raise TaskValidationError(
                f"{label}: Seed schema violation at {path} ({exc.validator})"
            ) from exc
        except Exception as exc:
            raise TaskValidationError(
                f"{label}: Seed schema validation failed ({type(exc).__name__})"
            ) from exc


def _require_local_schema_references(value: JsonValue) -> None:
    resource = Resource.from_contents(value, default_specification=DRAFT202012)
    pending = [resource]
    while pending:
        current = pending.pop()
        if isinstance(current.contents, dict):
            for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                if key in current.contents:
                    item = current.contents[key]
                    if not isinstance(item, str) or not item.startswith("#"):
                        raise ValueError(
                            "only document-local schema references are allowed"
                        )
        pending.extend(current.subresources())
