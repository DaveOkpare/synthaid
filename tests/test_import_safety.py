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
        assert main(sys.argv[1:]) == 0
    except SystemExit as exc:
        assert exc.code == 0

assert not violations, violations
"""


@pytest.mark.parametrize("operation", ["import", "--help", "--version", "validate"])
def test_startup_has_no_external_effects(operation: str, tmp_path: Path) -> None:
    # -B excludes interpreter bytecode caching from application effects; -I
    # prevents user site packages and PYTHONPATH from influencing the check.
    args = [sys.executable, "-I", "-B", "-c", STARTUP_CHECK, operation]
    if operation == "validate":
        args.append(str(Path(__file__).resolve().parents[1] / "examples/single-agent"))
    result = subprocess.run(
        args,
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


COLLECTION_CHECK = r"""
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
        blocked = args[0].split(".")[0] in {"openai", "vllm"}
    if blocked:
        violations.append(event)
        raise AssertionError(f"Unexpected collection effect: {event}")

sys.addaudithook(guard)
# Test modules may define fake HTTP transports, but collecting them must never
# initialize a client. This guard is at the third-party HTTP boundary.
import httpx
def client_init(*args, **kwargs):
    violations.append("httpx client construction")
    raise AssertionError("Collection initialized an HTTP client")
httpx.Client.__init__ = client_init
httpx.AsyncClient.__init__ = client_init
# Observe public runtime constructor entry without replacing framework behavior.
def model_construction(frame, event, arg):
    if event != "call" or frame.f_code.co_name != "__init__":
        return
    model_types = {
        ("agentinstruct.model_agent", "ModelAgent"),
        ("agentinstruct.providers", "ChatCompletionsProvider"),
        ("agentinstruct.providers", "ResponsesProvider"),
        ("agentinstruct.vllm", "VllmProvider"),
    }
    bases = type(frame.f_locals.get("self")).__mro__
    if any((base.__module__, base.__name__) in model_types for base in bases):
        violations.append("model construction")
        raise AssertionError("Collection initialized a model Agent or Provider")
sys.setprofile(model_construction)
if len(sys.argv) > 2:
    from agentinstruct import ChatCompletionsProvider, ProviderPlan
    plan = ProviderPlan(
        "test", "openai-compatible", "chat_completions",
        "https://unused.example/v1", None,
    )
    ChatCompletionsProvider(plan)
import pytest
assert pytest.main([
    sys.argv[1], "--collect-only", "-q", "-s", "-p", "no:cacheprovider",
    "-p", "no:logging", "-p", "pytest_asyncio.plugin", "--import-mode=importlib",
]) == 0
assert not violations, violations
"""


@pytest.mark.parametrize("probe", [False, True])
def test_test_collection_has_no_network_client_or_storage_effects(
    tmp_path: Path,
    probe: bool,
) -> None:
    import os

    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            COLLECTION_CHECK,
            str(Path(__file__).parent.resolve()),
            *(["construct-lazy-provider"] if probe else []),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if probe:
        assert result.returncode != 0
        assert "initialized a model Agent or Provider" in result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "tests collected" in result.stdout
    assert list(tmp_path.iterdir()) == []
