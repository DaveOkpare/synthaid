"""Command-line entry point for agentinstruct."""

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version


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
    validate.add_argument("--seed", help="Override the single JSON Seed path")
    validate.add_argument("--json", action="store_true", dest="as_json")
    run = commands.add_parser("run", help="Generate a durable Trace")
    run.add_argument("package", help="Task Package directory")
    run.add_argument("--seed", help="Override the single JSON Seed path")
    run.add_argument("--output", default="runs", help="Run output directory")
    run.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    if args.command == "validate":
        from agentinstruct.task_package import TaskPackage, TaskValidationError

        try:
            plan = TaskPackage.load(args.package).compile(seed_path=args.seed)
        except TaskValidationError as exc:
            if args.as_json:
                print(json.dumps({"status": "invalid", "error": str(exc)}))
            else:
                print(f"Validation failed: {exc}", file=sys.stderr)
            return 2
        if args.as_json:
            print(json.dumps({"status": "valid", "plan": plan.to_dict()}))
        else:
            print(
                f"Valid Task {plan.task.id}; Seed {plan.seed.id}; "
                f"Run Plan {plan.digest}"
            )
        return 0
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
            print(f"Run {result.run_id}: {counts}\n{result.path}")
        return 1 if result.counts["failed"] or result.counts["invalid"] else 0
    parser.print_help()
    return 0
