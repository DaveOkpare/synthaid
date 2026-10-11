"""Loads TOML task definitions and builds independent conversations."""

from collections.abc import Mapping
import dataclasses
import hashlib
import importlib
import importlib.util
import os
import pathlib
import sys
import tomllib
import types
from typing import Annotated, Literal, Self, TypeAlias

import pydantic

from synthaid import agent
from synthaid import evaluation
from synthaid import model
from synthaid import task
from synthaid import tool

_Text: TypeAlias = Annotated[str, pydantic.Field(min_length=1)]
_Limit: TypeAlias = Annotated[int, pydantic.Field(ge=1)]
_FiniteFloat: TypeAlias = Annotated[float, pydantic.Field(allow_inf_nan=False)]


class ConfigError(ValueError):
    """A task file, reference, or execution setting is invalid."""


class _Spec(pydantic.BaseModel):
    """Base for typed configuration, rejecting typos and coercion."""

    model_config = pydantic.ConfigDict(extra="forbid", strict=True)


class _Model(_Spec):
    """A model's connection settings, without resolved credentials."""

    model_name: _Text
    base_url: _Text
    api_key_env: _Text = "OPENAI_API_KEY"
    temperature: _FiniteFloat = 0.7


class _PythonRef(_Spec):
    """An exported Python object, from a file or an importable module."""

    file: _Text | None = None
    module: _Text | None = None
    object: _Text

    @pydantic.model_validator(mode="after")
    def _one_source(self) -> Self:
        if (self.file is None) == (self.module is None):
            raise ValueError("set exactly one of file or module")
        return self


class _Criterion(_Spec):
    """One criterion, before any judge answers it."""

    content: _Text
    weight: _FiniteFloat = 1.0


class _Evaluator(_Spec):
    """A built-in LLM judge definition."""

    kind: Literal["llm"]
    model: _Text
    criteria: list[_Criterion] = pydantic.Field(min_length=1)
    instructions: _Text | None = None
    threshold: _FiniteFloat | None = None


class _Agent(_Spec):
    """An agent's instructions, capabilities, and reflection limits."""

    model: _Text
    instructions: str
    tools: list[_Text] = pydantic.Field(default_factory=list)
    evaluator: _Text | None = None
    max_iterations: _Limit = 3
    max_tool_rounds: _Limit = 10


class _Step(_Spec):
    """One ordered part of the conversation."""

    instruction: _Text
    max_turns: _Limit = 1


class _Task(_Spec):
    """Participants and ordered conversation steps."""

    assistant: _Text
    user: _Text | None = None
    steps: list[_Step] = pydantic.Field(min_length=1)


class _Definitions(_Spec):
    """Versioned named definitions in a single TOML file."""

    schema_version: Annotated[int, pydantic.Field(ge=1, le=1)]
    models: dict[_Text, _Model] = pydantic.Field(min_length=1)
    tools: dict[_Text, _PythonRef] = pydantic.Field(default_factory=dict)
    evaluators: dict[_Text, _Evaluator] = pydantic.Field(default_factory=dict)
    agents: dict[_Text, _Agent] = pydantic.Field(min_length=1)
    tasks: dict[_Text, _Task] = pydantic.Field(min_length=1)


@dataclasses.dataclass(frozen=True)
class Config:
    """Validated definitions, loaded without importing tools or API keys.

    Use `task_names` to select a task, then `build()` to resolve the selected
    credentials and Python tools and create fresh agents and judges.
    """

    path: pathlib.Path
    _definitions: _Definitions = dataclasses.field(repr=False)

    @property
    def task_names(self) -> tuple[str, ...]:
        """Task names in their declaration order."""
        return tuple(self._definitions.tasks)

    def build(self, name: str) -> task.Task:
        """Builds one task with fresh state and no model requests.

        Args:
            name: A name from `task_names`.

        Returns:
            A Task ready for `environment.run()`.

        Raises:
            ConfigError: The task is unknown, a credential is missing,
                or a Python tool cannot be loaded or used.
        """
        if name not in self._definitions.tasks:
            raise ConfigError(f"{self.path}: unknown task {name!r}")
        models: dict[str, model.Model] = {}
        selected = self._definitions.tasks[name]
        try:
            assistant = self._build_agent(selected.assistant, models)
            steps = [
                task.Step(step.instruction, step.max_turns)
                for step in selected.steps
            ]
            user = None
            if selected.user is not None:
                user = self._build_agent(selected.user, models)
            return task.Task(assistant, steps, user=user)
        except ConfigError as error:
            raise ConfigError(f"{self.path}: {error}") from error

    def _build_agent(
        self, name: str, models: dict[str, model.Model]
    ) -> agent.Agent:
        spec = self._definitions.agents[name]
        evaluator = None
        if spec.evaluator is not None:
            evaluator = self._build_evaluator(spec.evaluator, models)
        tools = [
            _load_tool(
                self._definitions.tools[tool_name], self.path.parent, tool_name
            )
            for tool_name in spec.tools
        ]
        try:
            return agent.Agent(
                self._get_model(spec.model, models),
                spec.instructions,
                tools=tools,
                evaluator=evaluator,
                max_iterations=spec.max_iterations,
                max_tool_rounds=spec.max_tool_rounds,
            )
        except ValueError as error:
            raise ConfigError(f"agents.{name}: {error}") from error

    def _build_evaluator(
        self, name: str, models: dict[str, model.Model]
    ) -> evaluation.LLMJudge:
        spec = self._definitions.evaluators[name]
        criteria = [
            evaluation.Criterion(content=item.content, weight=item.weight)
            for item in spec.criteria
        ]
        options = {}
        if spec.instructions is not None:
            options["instructions"] = spec.instructions
        return evaluation.LLMJudge(
            self._get_model(spec.model, models),
            criteria,
            threshold=spec.threshold,
            **options,
        )

    def _get_model(
        self, name: str, models: dict[str, model.Model]
    ) -> model.Model:
        if name not in models:
            spec = self._definitions.models[name]
            api_key = os.environ.get(spec.api_key_env)
            if not api_key:
                raise ConfigError(
                    f"models.{name}.api_key_env: environment variable "
                    f"{spec.api_key_env!r} is not set"
                )
            models[name] = model.Model(
                spec.model_name, spec.base_url, api_key, spec.temperature
            )
        return models[name]


def load(path: str | os.PathLike[str]) -> Config:
    """Parses and validates one TOML file, without executing Python tools.

    Args:
        path: The task definition file.

    Returns:
        Validated definitions, with an absolute source path.

    Raises:
        ConfigError: The file cannot be read, parsed, or validated.
    """
    source = pathlib.Path(path).resolve()
    try:
        with source.open("rb") as stream:
            definitions = _Definitions.model_validate(tomllib.load(stream))
        _check_references(definitions, source.parent)
    except pydantic.ValidationError as error:
        details = "\n".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise ConfigError(f"{source}:\n{details}") from error
    except (OSError, ValueError) as error:
        raise ConfigError(f"{source}: {error}") from error
    return Config(source, definitions)


def discover(
    path: str | os.PathLike[str],
    *,
    recursive: bool = False,
    exclude: str | os.PathLike[str] | None = None,
) -> list[pathlib.Path]:
    """Finds TOML task files in sorted order.

    Directory discovery skips hidden paths and the optional output root.
    An explicitly selected file is never excluded.

    Args:
        path: A TOML file or a directory of task files.
        recursive: Whether to descend into subdirectories.
        exclude: An output directory to leave out of discovery.

    Returns:
        Absolute file paths, sorted for directory inputs.

    Raises:
        ConfigError: The path is missing, has an unsupported extension,
            or contains no TOML task files.
    """
    source = pathlib.Path(path).resolve()
    if source.is_file():
        if source.suffix != ".toml":
            raise ConfigError(f"{source}: expected a .toml task file")
        return [source]
    if not source.is_dir():
        raise ConfigError(f"{source}: not a file or directory")
    excluded = None if exclude is None else pathlib.Path(exclude).resolve()
    candidates = source.rglob("*.toml") if recursive else source.glob("*.toml")
    files = set()
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if any(
            part.startswith(".") for part in candidate.relative_to(source).parts
        ):
            continue
        resolved = candidate.resolve()
        if excluded is not None and resolved.is_relative_to(excluded):
            continue
        files.add(resolved)
    if not files:
        raise ConfigError(f"{source}: No TOML task files found")
    return sorted(files)


def _check_references(
    definitions: _Definitions, directory: pathlib.Path
) -> None:
    """Validates names and file existence without loading Python objects."""
    for name, ref in definitions.tools.items():
        if ref.file is not None and not (directory / ref.file).is_file():
            raise ConfigError(
                f"tools.{name}.file: file not found: {ref.file!r}"
            )
    for name, judge in definitions.evaluators.items():
        _check_reference(
            judge.model, definitions.models, f"evaluators.{name}.model"
        )
        contents = [item.content for item in judge.criteria]
        if len(set(contents)) != len(contents):
            raise ConfigError(f"evaluators.{name}.criteria: duplicate contents")
    for name, helper in definitions.agents.items():
        _check_reference(
            helper.model, definitions.models, f"agents.{name}.model"
        )
        if helper.evaluator is not None:
            _check_reference(
                helper.evaluator,
                definitions.evaluators,
                f"agents.{name}.evaluator",
            )
        if len(set(helper.tools)) != len(helper.tools):
            raise ConfigError(f"agents.{name}.tools: duplicate tool references")
        for index, key in enumerate(helper.tools):
            _check_reference(
                key, definitions.tools, f"agents.{name}.tools.{index}"
            )
    for name, selected in definitions.tasks.items():
        _check_reference(
            selected.assistant, definitions.agents, f"tasks.{name}.assistant"
        )
        if selected.user is not None:
            _check_reference(
                selected.user, definitions.agents, f"tasks.{name}.user"
            )
            if selected.user == selected.assistant:
                raise ConfigError(
                    f"tasks.{name}.user: must differ from assistant"
                )


def _check_reference(
    name: str, definitions: Mapping[str, object], field: str
) -> None:
    if name not in definitions:
        raise ConfigError(f"{field}: unknown reference {name!r}")


def _load_tool(
    ref: _PythonRef, directory: pathlib.Path, name: str
) -> tool.Tool:
    """Imports one selected Python reference and checks that it is a Tool."""
    try:
        if ref.file is not None:
            module = _import_file(directory / ref.file)
        elif ref.module is not None:
            module = importlib.import_module(ref.module)
        else:
            raise ValueError("set exactly one of file or module")
        result = getattr(module, ref.object)
        if not isinstance(result, tool.Tool):
            raise TypeError(f"{ref.object!r} must be a synthaid.tool.Tool")
        return result
    except Exception as error:
        raise ConfigError(f"tools.{name}: {error}") from error


def _import_file(path: pathlib.Path) -> types.ModuleType:
    """Imports a tool file once, without changing the import search path."""
    source = path.resolve()
    digest = hashlib.sha256(str(source).encode()).hexdigest()
    name = f"_synthaid_tools_{digest}"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import Python file: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module
