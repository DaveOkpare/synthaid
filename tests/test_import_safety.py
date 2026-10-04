"""Import, authoring validation and collection must acquire no live resources."""

import subprocess
import sys
from pathlib import Path

import pytest

GUARD = """
import os
import sys
violations = []
def guard(event, args):
    blocked = event.startswith("socket.") or event in {
        "os.mkdir", "os.remove", "os.rename", "os.link", "subprocess.Popen"
    }
    if event == "open":
        blocked = bool(args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
    if event == "import" and args[0].split(".")[0] in {"openai", "httpx", "vllm"}:
        blocked = True
    if blocked:
        violations.append(event)
        raise AssertionError("Unexpected startup effect: " + event)
sys.addaudithook(guard)
import agentinstruct
assert set(agentinstruct.__all__) == {
    "Agent", "Environment", "Episode", "Judge", "Runner", "Task", "Tool"
}
retired = {
    "TaskPackage", "FunctionTool", "ProviderRequest", "Seed", "Reviewer", "Verifier"
}
assert not retired & set(dir(agentinstruct))
if sys.argv[1] != "import":
    from agentinstruct.cli import main
    try:
        assert main(sys.argv[1:]) == 0
    except SystemExit as error:
        assert error.code == 0
assert not violations
"""


@pytest.mark.parametrize("operation", ["import", "--help", "--version", "validate"])
def test_core_and_cli_startup_are_inert(operation: str, tmp_path: Path) -> None:
    arguments = [sys.executable, "-I", "-B", "-c", GUARD, operation]
    if operation == "validate":
        arguments.append(
            str(Path(__file__).resolve().parents[1] / "examples/verified-single")
        )
    result = subprocess.run(
        arguments, cwd=tmp_path, capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not list(tmp_path.iterdir())


def test_agent_and_task_construction_do_not_import_sdk(tmp_path: Path) -> None:
    code = (
        GUARD.replace('if sys.argv[1] != "import":', "if False:")
        + """
from agentinstruct import Agent, Task
agent = Agent("model")
task = Task(agents={"assistant": agent})
assert task.episode.messages == ()
assert "openai" not in sys.modules
"""
    )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, "import"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
