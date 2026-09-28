"""Command-line entry point for agentinstruct."""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version

from agentinstruct.traces import STATUSES


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and display package information."""
    parser = argparse.ArgumentParser(
        prog="agentinstruct",
        description="Generate verified traces from agent interactions.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('agentinstruct')}",
    )
    commands = parser.add_subparsers(dest="command")
    validate = commands.add_parser(
        "validate", help="Compile a Task Package without model calls"
    )
    validate.add_argument("package", help="Task Package directory")
    validate.add_argument(
        "--seed", help="Override the JSON, JSONL, CSV, or directory Seed source"
    )
    validate.add_argument("--json", action="store_true", dest="as_json")
    run = commands.add_parser("run", help="Generate durable Traces from a Seed source")
    run.add_argument("package", help="Task Package directory")
    run.add_argument(
        "--seed", help="Override the JSON, JSONL, CSV, or directory Seed source"
    )
    run.add_argument("--output", default="runs", help="Run output directory")
    run.add_argument("--json", action="store_true", dest="as_json")
    run.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first invalid or failed Trace",
    )
    export = commands.add_parser("export", help="Export persisted Traces as JSONL")
    export.add_argument(
        "traces", nargs="+", help="Run/Trace directories or snapshot files"
    )
    export.add_argument("--format", choices=["native", "openai"], default="openai")
    export.add_argument("--output", required=True, help="Destination JSONL file")
    export.add_argument(
        "--status",
        choices=STATUSES,
        action="append",
        help="Include status (repeatable)",
    )
    for identity in ("run", "trace", "seed"):
        export.add_argument(
            f"--{identity}-id",
            action="append",
            help=f"Include {identity} ID (repeatable)",
        )
    export.add_argument("--json", action="store_true", dest="as_json")
    export.add_argument("--verification", help="Select a valid Verification attempt ID")
    reverification = commands.add_parser(
        "reverify", help="Append Verification attempts to sealed Traces"
    )
    reverification.add_argument(
        "traces", nargs="+", help="Trace directories or snapshots"
    )
    reverification.add_argument(
        "--package", help="Override with this Task Package's Verifier policy"
    )
    reverification.add_argument("--json", action="store_true", dest="as_json")
    from agentinstruct.inspection import VIEWS

    inspection = commands.add_parser("inspect", help="Inspect a persisted Run or Trace")
    inspection.add_argument(
        "path", help="Run directory, Trace directory or snapshot file"
    )
    display = inspection.add_mutually_exclusive_group()
    display.add_argument("--json", action="store_true", dest="as_json")
    display.add_argument(
        "--tui", action="store_true", help="Open read-only terminal navigation"
    )
    inspection.add_argument("--trace", type=int, help="Select a 1-based Trace in a Run")
    inspection.add_argument("--view", choices=VIEWS, default="summary")
    inspection.add_argument(
        "--participant", help="Participant ID for the participant view"
    )
    args = parser.parse_args(argv)
    if args.command == "inspect":
        from agentinstruct.inspection import Inspector, run_terminal, terminal_text

        try:
            inspector = Inspector(args.path)
            index = args.trace - 1 if args.trace is not None else None
            if index is not None and not 0 <= index < len(inspector.traces):
                raise ValueError("Trace number is out of range")
            if args.participant is not None and args.view != "participant":
                raise ValueError("--participant requires --view participant")
            data = (
                inspector.summary(trace_index=index)
                if args.view == "summary"
                else inspector.view(
                    args.view, trace_index=index or 0, participant=args.participant
                )
            )
            if args.tui:
                run_terminal(
                    inspector,
                    sys.stdin,
                    sys.stdout,
                    trace_index=index,
                    view=args.view,
                    participant=args.participant,
                )
            elif args.as_json:
                print(json.dumps(data))
            else:
                print(
                    inspector.render(
                        args.view, trace_index=index, participant=args.participant
                    )
                )
        except (OSError, ValueError, IndexError) as exc:
            if args.as_json:
                print(json.dumps({"status": "error", "error": str(exc)}))
            else:
                print(terminal_text(f"Inspection failed: {exc}"), file=sys.stderr)
            return 1
        return 0
    if args.command == "validate":
        from agentinstruct.task_package import TaskPackage, TaskValidationError

        try:
            report = TaskPackage.load(args.package).validate(seed_path=args.seed)
        except TaskValidationError as exc:
            if args.as_json:
                print(json.dumps({"status": "invalid", "error": str(exc)}))
            else:
                print(f"Validation failed: {exc}", file=sys.stderr)
            return 2
        if args.as_json:
            print(json.dumps(report.to_dict()))
        elif report.valid and len(report.records) == 1:
            plan = report.records[0].plan
            assert plan is not None
            print(
                f"Valid Task {plan.task.id}; Seed {plan.seed.id}; "
                f"Run Plan {plan.digest}"
            )
        elif report.valid:
            print(f"Valid Task Package; {len(report.records)} Seed records")
        else:
            print(f"Validation failed: {report.to_dict()['error']}", file=sys.stderr)
        return 0 if report.valid else 2
    if args.command == "run":
        from agentinstruct import (
            Runner,
            TaskPackage,
            TaskValidationError,
            generate_sync,
        )

        try:
            result = generate_sync(
                TaskPackage.load(args.package),
                runner=Runner(output_dir=args.output),
                seed_path=args.seed,
                fail_fast=args.fail_fast,
            )
        except (TaskValidationError, OSError) as exc:
            if args.as_json:
                print(json.dumps({"status": "error", "error": str(exc)}))
            else:
                print(f"Run failed: {exc}", file=sys.stderr)
            return 2 if isinstance(exc, TaskValidationError) else 1
        if args.as_json:
            print(json.dumps(result.to_dict()))
        else:
            counts = ", ".join(f"{key}={value}" for key, value in result.counts.items())
            print(f"Run {result.run_id}: {result.status}; {counts}\n{result.path}")
            if result.error is not None:
                print(result.error, file=sys.stderr)
        return (
            1
            if result.status == "failed"
            or result.counts["failed"]
            or result.counts["invalid"]
            else 0
        )
    if args.command == "export":
        from agentinstruct import export_native, export_openai

        exporter = export_native if args.format == "native" else export_openai
        try:
            count = exporter(
                args.traces,
                args.output,
                statuses=set(args.status or ["accepted"]),
                verification_id=args.verification,
                run_ids=set(args.run_id) if args.run_id is not None else None,
                trace_ids=set(args.trace_id) if args.trace_id is not None else None,
                seed_ids=set(args.seed_id) if args.seed_id is not None else None,
            )
        except (OSError, ValueError) as exc:
            if args.as_json:
                print(json.dumps({"status": "error", "error": str(exc)}))
            else:
                print(f"Export failed: {exc}", file=sys.stderr)
            return 1
        if args.as_json:
            print(
                json.dumps({"count": count, "format": args.format, "path": args.output})
            )
        else:
            print(f"Exported {count} Traces to {args.output}")
        return 0
    if args.command == "reverify":
        from agentinstruct import TaskPackage, TaskValidationError, reverify
        from agentinstruct.plans import json_value
        from agentinstruct.traces import VerificationAttempt

        async def append_attempts() -> list[VerificationAttempt]:
            package = None
            if args.package is not None:
                package = TaskPackage.load(args.package)
                if package.verifier is None:
                    raise ValueError("Selected Task Package has no Verifier policy")
            return [await reverify(path, package=package) for path in args.traces]

        try:
            attempts = asyncio.run(append_attempts())
        except (OSError, ValueError) as exc:
            if args.as_json:
                print(json.dumps({"status": "error", "error": str(exc)}))
            else:
                print(f"Reverification failed: {exc}", file=sys.stderr)
            return 2 if isinstance(exc, TaskValidationError) else 1
        if args.as_json:
            print(json.dumps({"attempts": [json_value(item) for item in attempts]}))
        else:
            for attempt in attempts:
                print(
                    f"Verification {attempt.id}: {attempt.status} "
                    f"(score={attempt.score})"
                )
        return 1 if any(item.status == "unverified" for item in attempts) else 0
    parser.print_help()
    return 0
