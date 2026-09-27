"""Exercise package startup with effects blocked at Python's system boundary."""

import subprocess
import sys
from pathlib import Path

import pytest

STARTUP_CHECK = """
import os
import sys

violations = []

def guard(event, args):
    blocked = event.startswith("socket.") or event in {
        "os.mkdir", "os.remove", "os.rename", "os.rmdir", "os.link", "os.symlink",
        "os.chmod", "os.truncate", "os.utime", "subprocess.Popen", "os.system",
    }
    if event == "open":
        blocked = bool(args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
    if event == "import":
        blocked = args[0].split(".")[0] in {"openai", "httpx", "vllm"}
    if blocked:
        violations.append(event)
        raise AssertionError(f"Unexpected startup effect: {event}")

sys.addaudithook(guard)

import agentinstruct

if sys.argv[1] != "import":
    from agentinstruct.cli import main
    try:
        main([sys.argv[1]])
    except SystemExit as exc:
        assert exc.code == 0

assert not violations, violations
"""


@pytest.mark.parametrize("operation", ["import", "--help", "--version"])
def test_startup_has_no_external_effects(operation: str, tmp_path: Path) -> None:
    # -B excludes interpreter bytecode caching from application effects; -I
    # prevents user site packages and PYTHONPATH from influencing the check.
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", STARTUP_CHECK, operation],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    if operation == "import":
        assert result.stdout == ""
    assert list(tmp_path.iterdir()) == []
