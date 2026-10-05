"""Optional command-line consumers of Tasks, Episodes and recorded inspection."""

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from contextlib import AsyncExitStack
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any

from agentinstruct.inspection import VIEWS, Inspector, terminal_text, trace_status


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
    _inspection_command(commands)
    _export_command(commands)
    commands.add_parser("vllm", help="Start a local vLLM server and run a program")
    return parser


def _task_commands(commands: Any) -> None:
    for name, handler in (("validate", _validate), ("run", _run)):
        parser = commands.add_parser(name)
        parser.set_defaults(handler=handler)
        parser.add_argument("package")
        parser.add_argument("--seed")
        parser.add_argument("--json", action="store_true", dest="as_json")
        if name == "run":
            parser.add_argument("--output", default="runs")
            parser.add_argument("--fail-fast", action="store_true")


def _inspection_command(commands: Any) -> None:
    parser = commands.add_parser("inspect")
    parser.set_defaults(handler=_inspect)
    parser.add_argument("path")
    parser.add_argument("--view", choices=VIEWS, default="summary")
    parser.add_argument("--trace", type=int)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tui", action="store_true")
    group.add_argument("--json", action="store_true", dest="as_json")


def _export_command(commands: Any) -> None:
    parser = commands.add_parser("export")
    parser.set_defaults(handler=_export)
    parser.add_argument("traces", nargs="+")
    parser.add_argument("--format", choices=["openai", "native"], default="openai")
    parser.add_argument("--output", required=True)
    for key in ("status", "trace-id"):
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
    return int(result["status"] == "failed" or result["counts"].get("invalid", 0) > 0)


async def _run_tasks(
    args: argparse.Namespace, report: dict[str, Any]
) -> dict[str, Any]:
    traces = []
    async with AsyncExitStack() as stack:
        clients = await _clients(stack, report["records"])
        for record in report["records"]:
            trace = await _execute_record(record, args.output, clients)
            traces.append(trace)
            if args.fail_fast and trace["status"] == "invalid":
                break
    result = _run_report(args.output, traces, report["source_error"])
    destination = Path(args.output) / "manifest.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, allow_nan=False) + "\n")
    return result


async def _execute_record(
    record: dict[str, Any], output: str, clients: dict[str, Any]
) -> dict[str, Any]:
    from agentinstruct import Runner
    from agentinstruct.adapters.task_files import task_from_record

    if record.get("error"):
        return dict(
            status="invalid", error=record["error"], origin=record.get("origin")
        )
    task = task_from_record(record, clients=clients)
    await Runner([task], output_dir=output).run()
    judgment = task.episode.verification
    verification = asdict(judgment) if judgment else None
    return {
        "trace_id": task.episode.id,
        "status": trace_status({"verification": verification}),
        "path": str(Path(task.episode.id) / "trace.json"),
    }


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
        agents = list(record["agents"].values())
        judges = [agent.get("reviewer") for agent in agents] + [record["verifier"]]
        for declaration in [*agents, *judges]:
            if declaration is None or declaration.get("type", "model") != "model":
                continue
            model = config.get("model", {}) | declaration.get("model", {})
            name = model.get("provider", "default")
            result[name] = config.get("providers", {}).get(name, {})
    return result


def _inspect(args: argparse.Namespace) -> int:
    inspector = Inspector(args.path)
    index = args.trace - 1 if args.trace is not None else None
    if index is not None and not 0 <= index < len(inspector.traces):
        raise ValueError("Trace number is out of range")
    if args.tui:
        from agentinstruct.ui.terminal import run_terminal

        run_terminal(
            inspector, sys.stdin, sys.stdout, trace_index=index, view=args.view
        )
    else:
        _inspect_output(inspector, args, index)
    return 0


def _export(args: argparse.Namespace) -> int:
    selected = [
        trace
        for path in args.traces
        for trace in Inspector(path).traces
        if _include(trace, args)
    ]
    with Path(args.output).open("x", encoding="utf-8") as stream:
        for trace in selected:
            row = trace if args.format == "native" else {"messages": trace["messages"]}
            stream.write(json.dumps(row, allow_nan=False) + "\n")
    _display({"count": len(selected), "path": args.output}, args.as_json)
    return 0


def _include(trace: dict[str, Any], args: argparse.Namespace) -> bool:
    return trace_status(trace) in (args.status or ["accepted"]) and (
        args.trace_id is None or trace["id"] in args.trace_id
    )


def _display(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, allow_nan=False))
    else:
        text = "\n".join(f"{k}: {v}" for k, v in value.items() if k != "records")
        print(terminal_text(text))


def _command(args: argparse.Namespace) -> int:
    try:
        handler: Callable[[argparse.Namespace], int] = args.handler
        return handler(args)
    except (ValueError, OSError, IndexError) as exc:
        _display({"status": "error", "error": str(exc)}, args.as_json)
        return 2 if isinstance(exc, ValueError) else 1


def _run_report(
    output: str, traces: Sequence[dict[str, Any]], source_error: str | None
) -> dict[str, Any]:
    return {
        "path": str(Path(output)),
        "status": "failed" if source_error else "finished",
        "counts": dict(Counter(t["status"] for t in traces)),
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


def _inspect_output(
    inspector: Inspector, args: argparse.Namespace, index: int | None
) -> None:
    if args.as_json:
        data = inspector.view(args.view, trace_index=index)
        print(json.dumps(data, allow_nan=False))
    else:
        print(inspector.render(args.view, trace_index=index))
