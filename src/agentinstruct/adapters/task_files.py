"""Optional inert authoring compilation and ordinary list[Task] preparation."""

import csv
import hashlib
import importlib
import re
import tomllib
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any

from jinja2 import StrictUndefined, TemplateError, Undefined, meta
from jinja2.sandbox import ImmutableSandboxedEnvironment

from agentinstruct import Agent, Judge, Task, Tool
from agentinstruct.episode import Message, canonical_json, json_data, parse_json
from agentinstruct.judge import Criterion, Rubric
from agentinstruct.tools import schema_validator


class TaskValidationError(ValueError):
    pass


class SourceError(ValueError):
    """A source could not enumerate record boundaries; distinct from a bad record."""


def _name(value: str) -> str:
    reserved = {"con", "prn", "aux", "nul"} | {
        f"{prefix}{i}" for prefix in ("com", "lpt") for i in range(1, 10)
    }
    if (
        not value
        or value in {".", ".."}
        or value[-1] in ". "
        or re.search(r'[\x00-\x1f<>:"/\\|?*]', value)
        or value.split(".")[0].casefold() in reserved
    ):
        raise TaskValidationError("Expected a portable identifier")
    return value


def _path(root: Path, relative: str) -> Path:
    value = Path(relative)
    if (
        value.is_absolute()
        or not value.parts
        or ".." in value.parts
        or "\\" in relative
    ):
        raise TaskValidationError("Expected a confined package-relative path")
    path = root
    for part in value.parts:
        _name(part)
        _exact_member(path, part)
        path /= part
        if path.is_symlink():
            raise TaskValidationError(f"{relative}: symbolic links are forbidden")
    return path


def _text(root: Path, relative: str) -> str:
    try:
        return _path(root, relative).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise TaskValidationError(f"{relative}: cannot read UTF-8 file") from exc


def _layout(root: Path, relative: str, expected: set[str]) -> None:
    path = _path(root, relative)
    actual = {item.name for item in path.iterdir()}
    if actual != expected:
        missing = ", ".join(sorted(expected - actual))
        extra = ", ".join(sorted(actual - expected))
        raise TaskValidationError(
            f"{relative}: missing [{missing}]; undeclared [{extra}]"
        )


def _template_value(value: Any) -> Any:
    if not isinstance(value, Undefined):
        canonical_json(value)
    return value


class _Templates(ImmutableSandboxedEnvironment):
    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        try:
            _template_value(value)
        except (ValueError, TypeError):
            return False
        return super().is_safe_attribute(obj, attr, value)


def _templates() -> _Templates:
    env = _Templates(
        undefined=StrictUndefined, keep_trailing_newline=True, finalize=_template_value
    )
    env.globals.clear()
    env.filters.pop("random")
    env.filters = {name: _data_filter(fn) for name, fn in env.filters.items()}
    return env


def _render(text: str, variables: Mapping[str, Any]) -> str:
    env = _templates()
    try:
        undeclared = meta.find_undeclared_variables(env.parse(text)) - set(variables)
        if undeclared:
            raise TaskValidationError(
                "Undeclared instruction variables: " + ", ".join(sorted(undeclared))
            )
        return env.from_string(text).render(json_data(variables))
    except (TemplateError, TypeError, ValueError) as exc:
        raise TaskValidationError(
            f"Instruction rendering failed ({type(exc).__name__})"
        ) from exc


def _configuration(root: Path) -> tuple[dict[str, Any], str]:
    text = _text(root, "task.toml")
    config = tomllib.loads(text)
    if config.get("schema_version") != "1" or set(config) - _TASK_FIELDS:
        raise TaskValidationError("Unsupported task schema or unknown task fields")
    _roles(config)
    _name(config["task"]["id"])
    _layout(root, "agents", set(config["agents"]))
    for role, agent in config["agents"].items():
        expected = {"instruction.md"} | (
            {"reviewer.md", "rubric.toml"} if agent.get("reviewer") else set()
        )
        _layout(root, f"agents/{role}", expected)
    _declarations(config)
    return config, text


def _roles(config: Mapping[str, Any]) -> None:
    agents = config.get("agents", {})
    if "assistant" not in agents or set(agents) - {"assistant", "user"}:
        raise TaskValidationError(
            "Migrate task roles to required assistant and optional user"
        )
    for role, settings in agents.items():
        if "target" in settings and settings["target"] is not (role == "assistant"):
            raise TaskValidationError("Target flags must identify only assistant")
    environment = config.get("environment", {})
    if environment.get("type", "single") not in {"single", "dialogue"}:
        raise TaskValidationError(
            "Use a direct structural Environment for custom scheduling"
        )
    if environment.get("type") == "dialogue" and "user" not in agents:
        raise TaskValidationError("Dialogue requires user and assistant")
    if config.get("runtime", {}).get("type", "local") != "local":
        raise TaskValidationError("Only local execution is supported")


def _files(root: Path, config: dict[str, Any], text: str) -> dict[str, str]:
    files = {"task.toml": text}
    for role, settings in config["agents"].items():
        names = [
            "instruction.md",
            *(["rubric.toml", "reviewer.md"] if settings.get("reviewer") else []),
        ]
        for name in names:
            label = f"agents/{role}/{name}"
            files[label] = _text(root, label)
    _verifier_files(root, config, files)
    _segment_files(root, config, files)
    if config["seed"].get("schema"):
        label = config["seed"]["schema"]
        files[label] = _text(root, label)
        schema_validator(parse_json(files[label]))
    return files


def _segment_files(
    root: Path, config: Mapping[str, Any], files: dict[str, str]
) -> None:
    steps = config["task"].get("steps", [])
    if not isinstance(steps, list) or len(steps) != len(set(steps)):
        raise TaskValidationError("Task steps must be an ordered unique list")
    if steps:
        _layout(root, "steps", set(steps))
    for step in steps:
        _name(step)
        _layout(root, f"steps/{step}/agents", set(config["agents"]))
        for role in config["agents"]:
            files.update(_phase_files(root, f"steps/{step}/agents/{role}"))


def _sources(path: Path, pattern: str | None) -> list[Path]:
    if path.is_symlink():
        raise SourceError("Source symbolic links are forbidden")
    if not path.is_dir():
        if not path.is_file():
            raise SourceError("Source must be a readable file or directory")
        return [path]
    if (
        not pattern
        or pattern.startswith("/")
        or ".." in pattern.split("/")
        or "\\" in pattern
    ):
        raise SourceError("Directory source requires a confined seed.glob")
    return _source_selection(path, pattern)


def _raw_records(path: Path) -> Iterator[tuple[int, Any, str | None]]:
    try:
        if path.suffix.lower() == ".csv":
            yield from _csv_records(path)
        elif path.suffix.lower() == ".jsonl":
            for index, raw in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if raw.strip():
                    yield index, raw, None
        elif path.suffix.lower() == ".json":
            yield from _json_records(path.read_text(encoding="utf-8"))
        else:
            raise SourceError("Unsupported source format")
    except (OSError, UnicodeError, csv.Error) as exc:
        raise SourceError(f"Cannot enumerate source ({type(exc).__name__})") from exc


def _json_records(raw: str) -> Iterator[tuple[int, str, None]]:
    from json import JSONDecodeError, JSONDecoder

    decoder = JSONDecoder()
    position, index = len(raw) - len(raw.lstrip()), 1
    array = raw[position : position + 1] == "["
    position += int(array)
    try:
        while raw[position:].lstrip()[:1] != "]":
            position += len(raw[position:]) - len(raw[position:].lstrip())
            _, end = decoder.raw_decode(raw, position)
            yield index, raw[position:end], None
            position, continued = _json_boundary(raw, end, array)
            if not continued:
                break
            index += 1
        _json_source_end(raw, position, array)
    except JSONDecodeError as exc:
        raise SourceError(f"Malformed JSON source at line {exc.lineno}") from exc


def _json_source_end(raw: str, position: int, array: bool) -> None:
    if array:
        if raw[position : position + 1] != "]":
            raise SourceError("Malformed JSON array boundary")
        position += 1
    if raw[position:].strip():
        raise SourceError("Extra data after JSON source")


def _csv_records(path: Path) -> Iterator[tuple[int, Any, str | None]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        headers = _csv_headers(next(reader, []))
        while True:
            index = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                return
            if row:
                yield _csv_row(index, headers, row)


def _inputs(
    root: Path,
    config: Mapping[str, Any],
    seed_path: str | Path | None,
    seeds: Iterable[Any] | None,
) -> Iterator[dict[str, Any]]:
    if seeds is not None:
        if seed_path is not None:
            raise SourceError("Choose seeds or seed_path")
        yield from _python_inputs(seeds)
    else:
        path = (
            Path(seed_path).absolute()
            if seed_path is not None
            else _path(root, config["seed"]["path"])
        )
        yield from _file_inputs(root, path, config["seed"].get("glob"))


def _select(data: Any, selector: str, flat: bool) -> Any:
    value = data
    for part in [selector] if flat else selector.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise TaskValidationError(
                f"Variable selector {selector!r} does not resolve"
            )
        value = value[part]
    return value


def compile_records(
    path: str | Path,
    *,
    seed_path: str | Path | None = None,
    seeds: Iterable[Any] | None = None,
) -> Iterator[dict[str, Any]]:
    root = Path(path).resolve(strict=True)
    config, text = _configuration(root)
    files = _files(root, config, text)
    seen: set[str] = set()
    for source in _inputs(root, config, seed_path, seeds):
        try:
            yield _compile_record(config, files, source, seen)
        except Exception as exc:
            yield _preparation_failure(config, source, exc)


def _compile_record(
    config: dict[str, Any],
    files: dict[str, str],
    source: dict[str, Any],
    seen: set[str],
) -> dict[str, Any]:
    data = _input_data(config, files, source)
    variables = _variables(data, config, source["origin"]["format"])
    identity = _input_identity(config, data, variables, seen)
    return dict(
        config=config,
        input=variables,
        agents=_agent_records(config, files, variables),
        segments=_segments(config, files, variables),
        provenance=_provenance(config["task"], files, identity, data, source["origin"]),
        verifier=_judge_record(config.get("verifier"), "verifier", files, variables),
    )


def _agent_records(
    config: Mapping[str, Any], files: Mapping[str, str], variables: Mapping[str, Any]
) -> dict[str, Any]:
    result = {}
    for role, settings in config["agents"].items():
        instruction = _render(files[f"agents/{role}/instruction.md"], variables)
        result[role] = {
            **settings,
            "instruction": instruction,
            "variables": variables,
            "model": {**config.get("model", {}), **settings.get("model", {})},
            "reviewer": _judge_record(
                settings.get("reviewer"), f"agents/{role}", files, variables
            ),
        }
    return result


def _segments(
    config: Mapping[str, Any], files: Mapping[str, str], variables: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "name": step,
            "instructions": {
                role: _render(files[label], variables)
                for role in config["agents"]
                if (label := f"steps/{step}/agents/{role}/instruction.md") in files
            },
        }
        for step in config["task"].get("steps", [])
    ]


def _judge_record(
    settings: Any, prefix: str, files: Mapping[str, str], variables: Mapping[str, Any]
) -> Any:
    if settings is None:
        return None
    rubric = tomllib.loads(files[prefix + "/rubric.toml"])
    for label, text in files.items():
        if (
            prefix.startswith("agents/")
            and label.startswith("steps/")
            and label.endswith(prefix + "/rubric.toml")
        ):
            rubric["criteria"].extend(tomllib.loads(text)["criteria"])
    _validate_judging(settings, rubric)
    suffix = "/reviewer.md" if prefix.startswith("agents/") else "/instruction.md"
    prompt = _render(
        files.get(prefix + suffix, "Evaluate accepted messages."), variables
    )
    return {**settings, "rubric": rubric, "prompt": prompt}


def _reference(reference: str) -> Any:
    _reference_syntax(reference)
    module, attribute = reference.split(":")
    value: Any = importlib.import_module(module)
    for name in attribute.split("."):
        value = getattr(value, name)
    return value


def _rubric(value: Any) -> Rubric:
    return Rubric(
        tuple(Criterion(**item) for item in value["criteria"]),
        value.get("threshold", 1.0),
    )


def _judge(
    settings: Any, config: Mapping[str, Any], client: Any, clients: Mapping[str, Any]
) -> Judge | None:
    if settings is None:
        return None
    rubric, kind = _rubric(settings["rubric"]), settings.get("type", "model")
    options = {"rubric": rubric, "timeout_seconds": settings.get("timeout_seconds")}
    if kind == "deterministic":
        checks = settings.get("checks", {})
        return Judge(
            check=lambda messages: _checks(messages, rubric, checks), **options
        )
    if kind != "model":
        return Judge(check=_reference(kind), **options)
    return Judge(**options, **_judge_model(settings, config, client, clients))


def _checks(
    messages: Sequence[Message], rubric: Rubric, checks: Mapping[str, str]
) -> dict[str, Any]:
    values = {
        "nonempty_content": bool(
            messages and (messages[-1].content.strip() or messages[-1].tool_calls)
        ),
        "nonempty_conversation": bool(messages),
        "assistant_present": any(m.actor_id == "assistant" for m in messages),
        "user_present": any(m.actor_id == "user" for m in messages),
    }
    return {
        "criteria": {
            item.id: values[checks.get(item.id, "nonempty_content")]
            for item in rubric.criteria
        },
        "feedback": "Provide a nonempty, valid response.",
    }


def _api(model: Mapping[str, Any], config: Mapping[str, Any]) -> str:
    return str(
        config.get("providers", {})
        .get(model.get("provider", "default"), {})
        .get("api", "chat_completions")
    )


def _client(
    model: Mapping[str, Any],
    config: Mapping[str, Any],
    client: Any,
    clients: Mapping[str, Any],
) -> Any:
    provider = model.get("provider", "default")
    if provider in clients:
        return clients[provider]
    endpoint = config.get("providers", {}).get(provider, {}).get("base_url")
    if (
        client is not None
        and endpoint
        and str(getattr(client, "base_url", "")).rstrip("/") != endpoint.rstrip("/")
    ):
        raise TaskValidationError(
            "Endpoint requires a separately initialized application-owned client"
        )
    return client


@dataclass(frozen=True)
class _Scripted:
    responses: Sequence[Any] = ()

    async def generate(
        self,
        history: Sequence[Message],
        *,
        client: Any = None,
        role: str = "assistant",
        instruction: str | None = None,
    ) -> Message:
        index = sum(m.actor_id == role and m.role != "tool" for m in history)
        if index >= len(self.responses):
            raise ValueError("Scripted Agent has no remaining response")
        value = self.responses[index]
        return (
            Message("assistant", value)
            if isinstance(value, str)
            else Message("assistant", value["content"], control=value.get("control"))
        )


def _tool(identifier: str, settings: Mapping[str, Any], variables: Any) -> Tool:
    kind = settings.get("type", "function")
    function = _reference(settings["function"] if kind == "function" else kind)
    if kind != "function":
        tool = function({"id": identifier, "variables": variables, **settings})
        if not isinstance(tool, Tool) or tool.id != identifier:
            raise TaskValidationError(
                "Custom Tool factories must return the declared Tool"
            )
        return tool
    return Tool(function, id=identifier, **_tool_options(settings))


def _agent(
    settings: Mapping[str, Any],
    config: Mapping[str, Any],
    client: Any,
    clients: Mapping[str, Any],
) -> Agent:
    options = _agent_options(settings, config)
    catalog = config.get("tools", {})
    options["tools"] = [
        _tool(name, catalog[name], settings.get("variables", {}))
        for name in settings.get("tools", [])
    ]
    options["reviewer"] = _judge(settings.get("reviewer"), config, client, clients)
    options["client"] = _client(settings["model"], config, client, clients)
    kind = settings.get("type", "model")
    if kind == "scripted":
        options["generator"] = _Scripted(tuple(settings.get("responses", ())))
    return _agent_class(kind)(**options)


def task_from_record(
    record: Mapping[str, Any],
    *,
    client: Any = None,
    clients: Mapping[str, Any] | None = None,
) -> Task:
    if record.get("error"):
        raise TaskValidationError(record["error"])
    config, dependencies = record["config"], clients or {}
    agents = {
        role: _agent(agent, config, client, dependencies)
        for role, agent in record["agents"].items()
    }
    verifier = _judge(record["verifier"], config, client, dependencies)
    values = {key: record[key] for key in ("input", "segments", "provenance")}
    return Task(agents=agents, verifier=verifier, **values, **_execution_limits(config))


def load_tasks(
    path: str | Path,
    *,
    seed_path: str | Path | None = None,
    seeds: Iterable[Any] | None = None,
    client: Any = None,
    clients: Mapping[str, Any] | None = None,
) -> list[Task]:
    return [
        task_from_record(record, client=client, clients=clients)
        for record in compile_records(path, seed_path=seed_path, seeds=seeds)
    ]


_TASK_FIELDS = {
    "schema_version",
    "task",
    "seed",
    "variables",
    "providers",
    "model",
    "agents",
    "environment",
    "runtime",
    "verifier",
    "tools",
}
_CHECKS = {
    "nonempty_content",
    "nonempty_conversation",
    "assistant_present",
    "user_present",
}
_MODEL_OPTIONS = (
    "temperature",
    "max_tokens",
    "reasoning",
    "extra_body",
    "output_schema",
)


def _exact_member(path: Path, part: str) -> None:
    members = list(path.iterdir())
    normalized = [
        unicodedata.normalize("NFC", item.name).casefold() for item in members
    ]
    if len(normalized) != len(set(normalized)) or part not in {
        item.name for item in members
    }:
        raise TaskValidationError(f"{part}: missing exact path or colliding names")


def _source_paths(files: Sequence[Path], root: Path) -> None:
    if any(item.is_symlink() for item in files):
        raise SourceError("Source directory contains symbolic links")
    normalized = [
        unicodedata.normalize("NFC", item.relative_to(root).as_posix()).casefold()
        for item in files
    ]
    if len(normalized) != len(set(normalized)):
        raise SourceError("Source paths collide after normalization")


def _verifier_files(
    root: Path, config: Mapping[str, Any], files: dict[str, str]
) -> None:
    if config.get("verifier"):
        files["verifier/rubric.toml"] = _text(root, "verifier/rubric.toml")
        if (root / "verifier/instruction.md").exists():
            files["verifier/instruction.md"] = _text(root, "verifier/instruction.md")


def _json_boundary(raw: str, end: int, array: bool) -> tuple[int, bool]:
    position = end + len(raw[end:]) - len(raw[end:].lstrip())
    if not array or raw[position : position + 1] != ",":
        return position, False
    position += 1
    if raw[position:].lstrip()[:1] == "]":
        raise SourceError("Trailing comma in JSON source")
    return position, True


def _python_inputs(seeds: Iterable[Any]) -> Iterator[dict[str, Any]]:
    try:
        for index, value in enumerate(seeds, 1):
            origin = {"path": "python:seeds", "record": index, "format": "python"}
            yield {"data": value, "origin": origin}
    except Exception as exc:
        raise SourceError("Python source iteration failed") from exc


def _input_data(
    config: Mapping[str, Any], files: Mapping[str, str], source: Mapping[str, Any]
) -> dict[str, Any]:
    if source.get("error"):
        raise TaskValidationError(source["error"])
    raw = source.get("raw")
    data = (
        parse_json(raw) if isinstance(raw, str) else json_data(source.get("data", raw))
    )
    if not isinstance(data, dict):
        raise TaskValidationError("Input record must be a JSON object")
    if config["seed"].get("schema"):
        schema_validator(parse_json(files[config["seed"]["schema"]])).validate(data)
    return data


def _input_identity(
    config: Mapping[str, Any], data: Any, variables: Mapping[str, Any], seen: set[str]
) -> str:
    identity = variables.get(
        config["seed"].get("id_variable"),
        hashlib.sha256(canonical_json(data).encode()).hexdigest(),
    )
    if (
        isinstance(identity, bool)
        or not isinstance(identity, (str, int))
        or not str(identity).strip()
        or str(identity) in seen
    ):
        raise TaskValidationError("Input identity must be nonempty and unique")
    seen.add(str(identity))
    return str(identity)


def _agent_options(
    settings: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    model, policy = settings["model"], settings.get("reviewer") or {}
    _model_declaration(model)
    options = {key: model[key] for key in _MODEL_OPTIONS if key in model}
    options.update(
        model=model.get("name"),
        instruction=settings.get("instruction", ""),
        api=_api(model, config),
        max_revisions=policy.get("max_revisions", 1),
        accept_on_revision_exhaustion=policy.get(
            "accept_on_revision_exhaustion", False
        ),
    )
    return options


def _execution_limits(config: Mapping[str, Any]) -> dict[str, Any]:
    settings = config.get("environment", {})
    return {
        key: settings[key]
        for key in ("max_rounds", "max_turns", "initiator", "timeout_seconds")
        if key in settings
    }


def _declarations(config: Mapping[str, Any]) -> None:
    for key, selector in config.get("variables", {}).items():
        if (
            not key.isidentifier()
            or not isinstance(selector, str)
            or not selector.strip()
        ):
            raise TaskValidationError(
                "Variables need identifiers and nonempty selectors"
            )
    _tool_declarations(config.get("tools", {}))
    _judge_declarations(config)
    agents = {
        role: _validate_agent(settings, config)
        for role, settings in config["agents"].items()
    }
    Task(agents=agents, **_execution_limits(config))


async def _declaration_only(arguments: Mapping[str, Any]) -> Any:
    raise RuntimeError("Authoring validation cannot execute capabilities")


def _tool_options(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: settings[key]
        for key in ("description", "input_schema", "output_schema", "execution_errors")
        if key in settings
    }


def _reference_syntax(reference: Any) -> None:
    if not isinstance(reference, str) or not re.fullmatch(
        r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", reference
    ):
        raise TaskValidationError(
            "Custom components require module:attribute references"
        )


def _validate_agent(settings: Mapping[str, Any], config: Mapping[str, Any]) -> Agent:
    assigned = settings.get("tools", [])
    if len(assigned) != len(set(assigned)) or set(assigned) - set(
        config.get("tools", {})
    ):
        raise TaskValidationError(
            "Agent Tool assignments must be unique declared names"
        )
    kind = settings.get("type", "model")
    if kind not in {"model", "scripted"}:
        _reference_syntax(kind)
    model = {**config.get("model", {}), **settings.get("model", {})}
    return Agent(**_agent_options({**settings, "model": model}, config))


def _validate_judging(settings: Mapping[str, Any], value: Any) -> None:
    rubric = _rubric(value)
    kind = settings.get("type", "model")
    if kind == "deterministic":
        checks = settings.get("checks", {})
        if (
            set(checks) - {item.id for item in rubric.criteria}
            or set(checks.values()) - _CHECKS
        ):
            raise TaskValidationError(
                "Migrate deterministic checks to accepted-message predicates"
            )
    elif kind != "model":
        _reference_syntax(kind)
    Judge(
        check=lambda messages: True,
        rubric=rubric,
        timeout_seconds=settings.get("timeout_seconds"),
    )


def _source_selection(path: Path, pattern: str) -> list[Path]:
    files = list(path.rglob("*"))
    _source_paths(files, path)
    selected = [
        item
        for item in files
        if item.is_file() and item.relative_to(path).full_match(pattern)
    ]
    return sorted(
        selected, key=lambda item: unicodedata.normalize("NFC", item.as_posix())
    )


def _csv_headers(headers: list[str]) -> list[str]:
    if (
        not headers
        or any(not value for value in headers)
        or len(headers) != len(set(headers))
    ):
        raise SourceError("CSV requires nonempty unique headers")
    return headers


def _csv_row(
    index: int, headers: Sequence[str], row: Sequence[str]
) -> tuple[int, Any, str | None]:
    data = dict(zip(headers, row, strict=True)) if len(row) == len(headers) else None
    return index, data, None if data is not None else "CSV row width mismatch"


def _file_inputs(
    root: Path, path: Path, pattern: str | None
) -> Iterator[dict[str, Any]]:
    for selected in _sources(path, pattern):
        label = (
            str(selected.relative_to(root))
            if selected.is_relative_to(root)
            else str(selected)
        )
        for index, raw, error in _raw_records(selected):
            origin = {
                "path": label,
                "record": index,
                "format": selected.suffix[1:].lower(),
            }
            yield {"raw": raw, "error": error, "origin": origin}


def _preparation_failure(
    config: Any, source: Mapping[str, Any], error: Exception
) -> dict[str, Any]:
    return {
        "error": f"Record preparation failed ({type(error).__name__}): {error}",
        "origin": source["origin"],
        "config": config,
        "source": source.get("raw"),
    }


def _provenance(
    task: Any, files: Any, identity: str, data: Any, origin: Any
) -> dict[str, Any]:
    return {
        "task": task,
        "seed": {"id": identity, "data": data, "origin": origin},
        "source_digest": hashlib.sha256(canonical_json(files).encode()).hexdigest(),
    }


def _judge_model(
    settings: Any, config: Mapping[str, Any], client: Any, clients: Mapping[str, Any]
) -> dict[str, Any]:
    model = {**config.get("model", {}), **settings.get("model", {})}
    return dict(
        client=_client(model, config, client, clients),
        model=model["name"],
        prompt=settings["prompt"],
        api=_api(model, config),
    )


def _agent_class(kind: str) -> type[Agent]:
    cls = {"model": Agent, "scripted": Agent}.get(kind) or _reference(kind)
    if not isinstance(cls, type) or not issubclass(cls, Agent):
        raise TaskValidationError(
            "Custom generation must subclass Agent and use its constructor"
        )
    return cls


def _tool_declarations(catalog: Mapping[str, Any]) -> None:
    for name, settings in catalog.items():
        _name(name)
        kind = settings.get("type", "function")
        _reference_syntax(settings.get("function") if kind == "function" else kind)
        Tool(_declaration_only, id=name, **_tool_options(settings))


def _data_filter(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def apply(*args: Any, **kwargs: Any) -> Any:
        value = function(*args, **kwargs)
        if isinstance(value, Iterator):
            value = list(value)
        return _template_value(value)

    return apply


def _variables(data: Any, config: Mapping[str, Any], format: str) -> dict[str, Any]:
    return {
        key: _select(data, selector, format == "csv")
        for key, selector in config.get("variables", {}).items()
    }


def _model_declaration(model: Mapping[str, Any]) -> None:
    if set(model) - {"name", "provider", *_MODEL_OPTIONS}:
        raise TaskValidationError(
            "Unknown model settings; use extra_body for endpoint options"
        )
    if "name" in model and (
        not isinstance(model["name"], str) or not model["name"].strip()
    ):
        raise TaskValidationError("Model name must be nonempty text")


def _judge_declarations(config: Mapping[str, Any]) -> None:
    judges = [
        agent["reviewer"]
        for agent in config["agents"].values()
        if agent.get("reviewer")
    ]
    if config.get("verifier"):
        judges.append(config["verifier"])
    for settings in judges:
        if settings.get("type", "model") == "model":
            model = {**config.get("model", {}), **settings.get("model", {})}
            _model_declaration(model)
            if not model.get("name"):
                raise TaskValidationError("Model Judge requires a declared model name")


def _phase_files(root: Path, prefix: str) -> dict[str, str]:
    path = _path(root, prefix)
    names = {item.name for item in path.iterdir()}
    if names - {"instruction.md", "rubric.toml"}:
        raise TaskValidationError("Unknown segment authoring files")
    return {
        f"{prefix}/{name}": _text(root, f"{prefix}/{name}") for name in sorted(names)
    }
