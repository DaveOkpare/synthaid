"""Smoke tests at the installed console-command boundary."""

import json
import os
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "single-agent"


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


def test_validate_reports_success_as_json(tmp_path: Path) -> None:
    result = run_command(["validate", str(EXAMPLE), "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "valid"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_validate_forwards_seed_override(tmp_path: Path) -> None:
    seed_path = tmp_path / "other.json"
    seed_path.write_text(
        '{"case":{"id":"other"},"person":{"name":"Lin"},"scenario":{"topic":"music"}}',
        encoding="utf-8",
    )

    result = run_command(
        ["validate", str(EXAMPLE), "--seed", "other.json", "--json"], tmp_path
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["plan"]["seed"]["id"] == "other"
    assert result.stderr == ""


@pytest.mark.parametrize("as_json", [False, True])
def test_validate_reports_precise_failure(tmp_path: Path, as_json: bool) -> None:
    seed_path = tmp_path / "broken.json"
    seed_path.write_text("{", encoding="utf-8")
    args = ["validate", str(EXAMPLE), "--seed", str(seed_path)]
    if as_json:
        args.append("--json")

    result = run_command(args, tmp_path)

    assert result.returncode == 2
    if as_json:
        output = json.loads(result.stdout)
        assert output["status"] == "invalid"
        assert "malformed JSON at line 1, column 2" in output["error"]
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert "Validation failed:" in result.stderr
        assert "malformed JSON at line 1, column 2" in result.stderr


def test_validate_reports_nonfinite_json_as_validation_failure(tmp_path: Path) -> None:
    seed_path = tmp_path / "broken.json"
    seed_path.write_text('{"value": NaN}', encoding="utf-8")

    result = run_command(
        ["validate", str(EXAMPLE), "--seed", str(seed_path), "--json"], tmp_path
    )

    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "invalid"
    assert "non-finite" in output["error"]
    assert result.stderr == ""
