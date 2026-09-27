"""Command-line entry point for agentinstruct."""

import argparse
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
    parser.parse_args(argv)
    parser.print_help()
    return 0
