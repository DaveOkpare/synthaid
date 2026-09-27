"""Smoke tests at the installed console-command boundary."""

import os
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agentinstruct", *args],
        cwd=cwd,
        env={
            **{
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT")
                if key in os.environ
            },
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_installed_command_reports_distribution_version(tmp_path: Path) -> None:
    result = run_command(["--version"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"agentinstruct {version('agentinstruct')}\n"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_installed_command_rejects_unknown_arguments(tmp_path: Path) -> None:
    result = run_command(["--unknown-option"], tmp_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unrecognized arguments: --unknown-option" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [[], ["--help"], ["-h"]])
def test_installed_command_shows_help(args: list[str], tmp_path: Path) -> None:
    result = run_command(args, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "usage: agentinstruct" in result.stdout
    assert "--help" in result.stdout
    assert "--version" in result.stdout
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []
