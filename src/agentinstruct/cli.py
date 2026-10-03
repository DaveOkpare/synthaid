"""Optional command-line consumers of Tasks, Episodes and recorded inspection."""

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from contextlib import AsyncExitStack
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agentinstruct.episode import Episode, canonical_json, output_path, write_json


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["vllm"]:
        from agentinstruct.integrations.vllm.serve import main as launch

        return launch(arguments[1:])
    parser = _parser()
    args = parser.parse_args(arguments)
    if args.command is None:
        parser.print_help()
        return 0
    return _command(args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentinstruct", description="Generate reviewed synthetic data."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('agentinstruct')}"
    )
    commands = parser.add_subparsers(dest="command")
    _task_commands(commands)
    _recorded_commands(commands)
    commands.add_parser("vllm", help="Start a local vLLM server and run a program")
    return parser


def _task_commands(commands: Any) -> None:
    for name in ("validate", "run"):
        parser = commands.add_parser(name)
        parser.add_argument("package")
        parser.add_argument("--seed")
        parser.add_argument("--json", action="store_true", dest="as_json")
        if name == "run":
            parser.add_argument("--output", default="runs")
            parser.add_argument("--fail-fast", action="store_true")


def _recorded_commands(commands: Any) -> None:
    from agentinstruct.inspection import VIEWS

    parser = commands.add_parser("inspect")
    parser.add_argument("path")
    parser.add_argument("--view", choices=VIEWS, default="summary")
    parser.add_argument("--trace", type=int)
    parser.add_argument("--participant")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tui", action="store_true")
    group.add_argument("--json", action="store_true", dest="as_json")
    _export_command(commands)
    parser = commands.add_parser("reverify")
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--package", required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")


def _export_command(commands: Any) -> None:
    parser = commands.add_parser("export")
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--format", choices=["openai", "native"], default="openai")
    parser.add_argument("--output", required=True)
    parser.add_argument("--verification")
    for key in ("status", "run-id", "trace-id", "seed-id"):
        parser.add_argument("--" + key, action="append")
    parser.add_argument("--json", action="store_true", dest="as_json")


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    from agentinstruct.adapters.task_files import SourceError, compile_records

    records: list[dict[str, Any]] = []
    source_error = None
    try:
        records.extend(compile_records(args.package, seed_path=args.seed))
    except SourceError as exc:
        source_error = str(exc)
    invalid = sum(bool(record.get("error")) for record in records)
    return {
        "status": "invalid" if invalid or source_error else "valid",
        "records": records,
        "counts": {"valid": len(records) - invalid, "invalid": invalid},
        "source_error": source_error,
    }


def _validate(args: argparse.Namespace) -> int:
    report = _prepare(args)
    _display(report, args.as_json)
    return int(report["status"] != "valid") * 2


def _run(args: argparse.Namespace) -> int:
    result = asyncio.run(_run_tasks(args, _prepare(args)))
    _display(result, args.as_json)
    return int(
        result["status"] == "failed"
        or result["counts"].get("failed", 0)
        or result["counts"].get("invalid", 0)
    )


async def _run_tasks(
    args: argparse.Namespace, report: dict[str, Any]
) -> dict[str, Any]:
    episodes: list[Episode] = []
    async with AsyncExitStack() as stack:
        clients = await _clients(stack, report["records"])
        for record in report["records"]:
            episode = await _execute_record(record, args.output, clients)
            episodes.append(episode)
            if args.fail_fast and episode.status in {"invalid", "failed"}:
                break
    result = _run_report(args.output, episodes, report["source_error"])
    destination = output_path(Path(args.output) / "manifest.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    write_json(destination, result)
    return result


async def _execute_record(
    record: dict[str, Any], output: str, clients: dict[str, Any]
) -> Episode:
    from agentinstruct import Runner
    from agentinstruct.adapters.task_files import task_from_record

    if record.get("error"):
        return _invalid_record(record, output)
    try:
        task = task_from_record(record, clients=clients)
    except Exception as exc:
        origin = record["provenance"]["seed"]["origin"]
        return _invalid_record({"error": type(exc).__name__, "origin": origin}, output)
    try:
        await Runner([task], output_dir=output).run()
    except Exception:
        if not task.episode.sealed:
            raise
    return task.episode


def _invalid_record(record: dict[str, Any], output: str) -> Episode:
    episode = Episode()
    episode.open(Path(output) / episode.id)
    episode.begin(
        {"source": record.get("origin"), "preparation_error": record["error"]}
    )
    episode.record("preparation_error", error=record["error"])
    episode.seal("invalid", "preparation")
    return episode


async def _clients(
    stack: AsyncExitStack, records: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    declarations = _client_declarations(records)
    if not declarations:
        return {}
    from openai import AsyncOpenAI

    result = {}
    for name, settings in declarations.items():
        client = AsyncOpenAI(**_client_options(settings))
        result[name] = await stack.enter_async_context(client)
    return result


def _client_declarations(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for record in records:
        if record.get("error"):
            continue
        config = record["config"]
        for declaration in _model_declarations(record):
            model = {**config.get("model", {}), **declaration.get("model", {})}
            name = model.get("provider", "default")
            result[name] = config.get("providers", {}).get(name, {})
    return result


def _inspect(args: argparse.Namespace) -> int:
    from agentinstruct.inspection import Inspector

    inspector = Inspector(args.path)
    index = args.trace - 1 if args.trace is not None else None
    if index is not None and not 0 <= index < len(inspector.traces):
        raise ValueError("Trace number is out of range")
    if args.tui:
        from agentinstruct.ui.terminal import run_terminal

        options = {
            "trace_index": index,
            "view": args.view,
            "participant": args.participant,
        }
        run_terminal(inspector, sys.stdin, sys.stdout, **options)
    else:
        _inspect_output(inspector, args, index)
    return 0


def _export(args: argparse.Namespace) -> int:
    from agentinstruct.inspection import Inspector

    episodes = [e for path in args.traces for e in Inspector(path).traces]
    selected = [e for e in episodes if _include(e, args)]
    destination = output_path(args.output)
    if any(e.path is not None and destination.is_relative_to(e.path) for e in episodes):
        raise ValueError("Export cannot overwrite recorded evidence")
    rows = [_export_row(e, args.format, args.verification) for e in selected]
    with destination.open("x", encoding="utf-8") as stream:
        for row in rows:
            stream.write(canonical_json(row) + "\n")
    _display({"count": len(rows), "path": str(destination)}, args.as_json)
    return 0


def _include(episode: Episode, args: argparse.Namespace) -> bool:
    if _verification_status(episode, args.verification) not in (
        args.status or ["accepted"]
    ):
        return False
    identity = episode.to_dict()
    return all(
        values is None or identity[key] in values
        for key, values in (
            ("run_id", args.run_id),
            ("trace_id", args.trace_id),
            ("seed_id", args.seed_id),
        )
    )


def _reverify(args: argparse.Namespace) -> int:
    from agentinstruct.adapters.task_files import load_tasks

    async def apply() -> list[MappingResult]:
        async with AsyncExitStack() as stack:
            report = _prepare(argparse.Namespace(package=args.package, seed=None))
            clients = await _clients(stack, report["records"])
            judge = load_tasks(args.package, clients=clients)[0].verifier
            if judge is None:
                raise ValueError("Task files have no verifier policy")
            return [
                dict(await Episode.load(path).verify(judge)) for path in args.traces
            ]

    attempts = asyncio.run(apply())
    _display({"attempts": attempts}, args.as_json)
    return int(any(item["status"] == "unverified" for item in attempts))


type MappingResult = dict[str, Any]


def _display(value: dict[str, Any], as_json: bool) -> None:
    from agentinstruct.inspection import terminal_text

    print(
        canonical_json(value)
        if as_json
        else terminal_text(
            "\n".join(
                f"{key}: {item}" for key, item in value.items() if key != "records"
            )
        )
    )


def _command(args: argparse.Namespace) -> int:
    handlers = {
        "validate": _validate,
        "run": _run,
        "inspect": _inspect,
        "export": _export,
        "reverify": _reverify,
    }
    try:
        return handlers[args.command](args)
    except (ValueError, OSError, IndexError) as exc:
        _display(
            {"status": "error", "error": str(exc)}, getattr(args, "as_json", False)
        )
        return 2 if isinstance(exc, ValueError) else 1


def _run_report(
    output: str, episodes: Sequence[Episode], source_error: str | None
) -> dict[str, Any]:
    from collections import Counter

    traces = [
        {"trace_id": e.id, "status": e.status, "path": e.path.name if e.path else ""}
        for e in episodes
    ]
    return {
        "path": str(Path(output)),
        "status": "failed" if source_error else "finished",
        "counts": dict(Counter(e.status for e in episodes)),
        "source_error": source_error,
        "traces": traces,
    }


def _client_options(settings: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get(settings.get("api_key_env") or "OPENAI_API_KEY")
    if key is None:
        raise ValueError(
            "Model client requires its configured credential environment variable"
        )
    return {
        "base_url": settings.get("base_url") or os.environ.get("MODEL_BASE_URL"),
        "api_key": key,
        "max_retries": 0,
    }


def _model_declarations(record: dict[str, Any]) -> list[dict[str, Any]]:
    agents = list(record["agents"].values())
    judges = [agent["reviewer"] for agent in agents if agent.get("reviewer")]
    if record["verifier"]:
        judges.append(record["verifier"])
    return [
        settings
        for settings in [*agents, *judges]
        if settings.get("type", "model") == "model"
    ]


def _inspect_output(
    inspector: Any, args: argparse.Namespace, index: int | None
) -> None:
    if args.as_json:
        data = (
            inspector.summary(trace_index=index)
            if args.view == "summary"
            else inspector.view(
                args.view, trace_index=index or 0, participant=args.participant
            )
        )
        print(canonical_json(data))
    else:
        print(
            inspector.render(args.view, trace_index=index, participant=args.participant)
        )


def _verification_status(episode: Episode, identifier: str | None) -> str:
    if identifier is None:
        return episode.status
    selected = next(
        (attempt for attempt in episode.verification if attempt["id"] == identifier),
        None,
    )
    if selected is None:
        raise ValueError("Unknown Verification ID")
    if episode.generation.get("state") in {"failed", "invalid"}:
        return episode.status
    return str(selected["status"])


def _export_row(
    episode: Episode, format: str, verification: str | None
) -> dict[str, Any]:
    if format == "openai":
        return {"messages": episode.training_messages()}
    data = episode.to_dict()
    data["status"] = _verification_status(episode, verification)
    data["selected_verification_id"] = verification
    return data
