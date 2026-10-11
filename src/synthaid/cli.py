"""Validates and runs TOML tasks from a file or directory."""

import argparse
from collections.abc import Sequence
import pathlib
import sys

from synthaid import config
from synthaid import environment
from synthaid import export
from synthaid import task


def main(argv: Sequence[str] | None = None) -> int:
    """Runs the CLI and returns its process exit code.

    Args:
        argv: Arguments without the program name, or None for sys.argv.

    Returns:
        0 on success, 1 when a run or save failed, 2 for invalid input or
        preparation failure, and 130 when interrupted.
    """
    args = _create_parser().parse_args(argv)
    try:
        if args.command == "run" and args.task and not args.path.is_file():
            raise config.ConfigError("--task requires a single TOML file")
        paths = config.discover(
            args.path, recursive=args.recursive, exclude=args.root
        )
        configs = [config.load(path) for path in paths]
        if args.command == "validate":
            for task_config in configs:
                names = ", ".join(task_config.task_names)
                print(f"valid {task_config.path}: {names}")
            return 0
        prepared = []
        for task_config in configs:
            task_names = (args.task,) if args.task else task_config.task_names
            for name in task_names:
                label = f"{task_config.path}:{name}"
                prepared.append((label, task_config.build(name)))
        args.root.mkdir(parents=True, exist_ok=True)
        failed = 0
        for label, conversation in prepared:
            if not _run(label, conversation, args.root):
                failed += 1
        print(f"{len(prepared) - failed} completed, {failed} failed")
        return 1 if failed else 0
    except (config.ConfigError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synthaid", description="Generate conversations from TOML tasks."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Validate task definitions without model requests."),
        ("run", "Run tasks and save each exchange and its agent logs."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument(
            "path", type=pathlib.Path, help="TOML file or directory"
        )
        command.add_argument(
            "--recursive",
            action="store_true",
            help="Include TOML task files in subdirectories.",
        )
        command.add_argument(
            "--root",
            type=pathlib.Path,
            default=pathlib.Path("runs"),
            help="Output root (default: ./runs); excluded from discovery.",
        )
        if name == "run":
            command.add_argument(
                "--task", help="Select one task from a single file."
            )
    return parser


def _run(label: str, conversation: task.Task, root: pathlib.Path) -> bool:
    """Runs and saves one task, retaining errors without stopping the batch."""
    print(f"running {label}", flush=True)
    succeeded = True
    try:
        environment.run(conversation)
    except Exception as error:
        print(
            f"failed {label}: {type(error).__name__}: {error}", file=sys.stderr
        )
        succeeded = False
    finally:
        try:
            directory = export.save(conversation, root)
            print(f"saved {label} to {directory}")
        except Exception as error:
            print(f"failed to save {label}: {error}", file=sys.stderr)
            succeeded = False
    return succeeded
