"""Local startup uses fake processes and HTTP transports, never a model server."""

import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from agentinstruct import cli
from agentinstruct.integrations.vllm import serve as launcher


@dataclass
class FakeProcess:
    pid: int
    returncode: int | None = None
    interrupt: bool = False
    terminate: bool = False
    ignore_term: bool = False

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt
        if self.terminate:
            self.terminate = False
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)
        if self.returncode is None:
            assert timeout is not None
            raise subprocess.TimeoutExpired("fake process", timeout)
        return self.returncode


@dataclass
class Harness:
    processes: list[FakeProcess] = field(default_factory=list)
    commands: list[tuple[list[str], dict[str, Any]]] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    signals: list[tuple[int, int]] = field(default_factory=list)
    responses: list[int | Exception] = field(default_factory=lambda: [200])
    now: float = 0
    server_code: int | None = None
    command_code: int | None = 0
    interrupt_command: bool = False
    terminate_command: bool = False
    terminate_on_health: bool = False
    ignore_term: bool = False
    start_failure: str | None = None


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    state = Harness()
    original_client = httpx.Client

    def start(command: list[str], **kwargs: Any) -> FakeProcess:
        server = not state.processes
        state.events.append("server" if server else "program")
        state.commands.append((command, kwargs))
        if state.start_failure == ("server" if server else "program"):
            raise FileNotFoundError("Missing interpreter or program")
        process = FakeProcess(
            pid=90000 + len(state.processes),
            returncode=state.server_code if server else state.command_code,
            interrupt=not server and state.interrupt_command,
            terminate=not server and state.terminate_command,
            ignore_term=state.ignore_term,
        )
        state.processes.append(process)
        return process

    def stop(pid: int, sig: int) -> None:
        state.signals.append((pid, sig))
        process = next(process for process in state.processes if process.pid == pid)
        if sig != signal.SIGTERM or not process.ignore_term:
            process.returncode = -sig

    def request(request: httpx.Request) -> httpx.Response:
        state.events.append(str(request.url))
        if state.terminate_on_health:
            state.terminate_on_health = False
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler)
            handler(signal.SIGTERM, None)
        response = state.responses.pop(0) if state.responses else 200
        if isinstance(response, Exception):
            raise response
        return httpx.Response(response)

    def client(**kwargs: Any) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(request), **kwargs)

    def sleep(seconds: float) -> None:
        state.now += seconds

    monkeypatch.setattr(subprocess, "Popen", start)
    monkeypatch.setattr(os, "killpg", stop)
    monkeypatch.setattr(socket, "socket", MagicMock)
    monkeypatch.setattr(httpx, "Client", client)
    monkeypatch.setattr(time, "monotonic", lambda: state.now)
    monkeypatch.setattr(time, "sleep", sleep)
    return state


def assert_stopped(state: Harness) -> None:
    assert state.processes
    assert all(process.poll() is not None for process in state.processes)
    owned = {process.pid for process in state.processes}
    assert {pid for pid, _ in state.signals} <= owned


def test_server_launches_once_and_waits_for_health(harness: Harness) -> None:
    harness.responses = [httpx.ConnectError("booting"), 503, 200]

    with launcher.vllm_server(
        "vendor/model",
        port=18123,
        python="/server/venv/bin/python",
        server_args=["--dtype", "auto"],
    ) as base_url:
        assert base_url == "http://127.0.0.1:18123/v1"
        assert len(harness.processes) == 1
        assert harness.processes[0].poll() is None
        assert harness.events == ["server", *["http://127.0.0.1:18123/health"] * 3]

    command, options = harness.commands[0]
    assert command == [
        "/server/venv/bin/python",
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        "vendor/model",
        "--host",
        "127.0.0.1",
        "--port",
        "18123",
        "--dtype",
        "auto",
    ]
    assert options.get("start_new_session") is True
    assert not options.get("shell", False)
    assert_stopped(harness)


def test_early_server_exit_does_not_yield(harness: Harness) -> None:
    harness.server_code = 7
    with (
        pytest.raises(RuntimeError, match=r"(?i)(exit|stopp)"),
        launcher.vllm_server("vendor/model"),
    ):
        pytest.fail("Generation cannot begin after a failed boot")
    assert_stopped(harness)


def test_unhealthy_server_has_a_deadline_and_is_stopped(harness: Harness) -> None:
    harness.responses = [503] * 100
    with (
        pytest.raises(TimeoutError, match=r"(?i)(time|ready|health)"),
        launcher.vllm_server("vendor/model", startup_timeout=0.3),
    ):
        pytest.fail("Generation cannot begin without a healthy server")
    assert harness.now >= 0.3
    assert_stopped(harness)


def test_body_failure_stops_only_the_owned_server(harness: Harness) -> None:
    with (
        pytest.raises(ValueError, match="generation failed"),
        launcher.vllm_server("vendor/model"),
    ):
        raise ValueError("generation failed")
    assert_stopped(harness)
    assert any(sig == signal.SIGTERM for _, sig in harness.signals)


def test_cleanup_escalates_when_owned_server_ignores_term(harness: Harness) -> None:
    harness.ignore_term = True
    with launcher.vllm_server("vendor/model"):
        pass
    assert any(sig == signal.SIGKILL for _, sig in harness.signals)
    assert_stopped(harness)


@pytest.mark.parametrize("during_readiness", [False, True])
def test_python_context_cleans_up_on_sigterm(
    during_readiness: bool, harness: Harness
) -> None:
    previous = signal.getsignal(signal.SIGTERM)
    harness.terminate_on_health = during_readiness
    with pytest.raises(SystemExit) as error, launcher.vllm_server("vendor/model"):
        assert not during_readiness, "SIGTERM should interrupt readiness"
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        handler(signal.SIGTERM, None)
    assert error.value.code == 143
    assert signal.getsignal(signal.SIGTERM) is previous
    assert_stopped(harness)


def test_program_runs_after_readiness_and_preserves_exit_code(harness: Harness) -> None:
    harness.responses = [503, 200]
    harness.command_code = 9
    assert (
        cli.main(
            [
                "vllm",
                "--model",
                "vendor/model",
                "--server-args",
                '--dtype auto --served-model-name "domain model"',
                "--",
                sys.executable,
                "generate.py",
                "literal;argument",
            ]
        )
        == 9
    )
    assert harness.events == [
        "server",
        "http://127.0.0.1:8000/health",
        "http://127.0.0.1:8000/health",
        "program",
    ]
    assert harness.commands[0][0][-4:] == [
        "--dtype",
        "auto",
        "--served-model-name",
        "domain model",
    ]
    program, options = harness.commands[1]
    assert program == [sys.executable, "generate.py", "literal;argument"]
    assert options.get("start_new_session") is True
    assert not options.get("shell", False)
    assert_stopped(harness)


@pytest.mark.parametrize("termination", [False, True])
def test_interruption_cleans_up_server_and_program(
    termination: bool, harness: Harness
) -> None:
    harness.command_code = None
    harness.interrupt_command = not termination
    harness.terminate_command = termination
    previous = signal.getsignal(signal.SIGTERM)
    assert launcher.main(["--model", "vendor/model", "--", "generate"]) == (
        143 if termination else 130
    )
    assert signal.getsignal(signal.SIGTERM) is previous
    assert len(harness.processes) == 2
    assert_stopped(harness)


def test_cli_requires_a_program_before_starting(harness: Harness) -> None:
    with pytest.raises(SystemExit) as error:
        launcher.main(["--model", "vendor/model"])
    assert error.value.code == 2
    assert harness.processes == []


@pytest.mark.parametrize(
    "options",
    [["--port", "0"], ["--startup-timeout", "0"], ["--startup-timeout", "nan"]],
)
def test_invalid_settings_do_not_start_processes(
    options: list[str], harness: Harness
) -> None:
    assert launcher.main(["--model", "vendor/model", *options, "--", "generate"]) == 1
    assert harness.processes == []


@pytest.mark.parametrize("server_args", [["--host=0.0.0.0"], ["--port", "9000"]])
def test_server_arguments_cannot_redirect_readiness(
    server_args: list[str], harness: Harness
) -> None:
    with (
        pytest.raises(ValueError, match=r"(?i)(host|port)"),
        launcher.vllm_server("vendor/model", server_args=server_args),
    ):
        pytest.fail("A mismatched readiness URL cannot be used")
    assert harness.processes == []


def test_busy_port_does_not_connect_to_or_stop_an_existing_server(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = MagicMock()
    probe.__enter__.return_value = probe
    probe.bind.side_effect = OSError("address already in use")
    monkeypatch.setattr(socket, "socket", lambda: probe)
    with (
        pytest.raises(RuntimeError, match="port"),
        launcher.vllm_server("vendor/model"),
    ):
        pytest.fail("The launcher must own the server it uses")
    assert harness.events == []
    assert harness.processes == []
    assert harness.signals == []


@pytest.mark.parametrize("missing", ["server", "program"])
def test_missing_interpreter_or_program_cleans_up_owned_processes(
    missing: str, harness: Harness
) -> None:
    previous = signal.getsignal(signal.SIGTERM)
    harness.start_failure = missing
    assert launcher.main(["--model", "vendor/model", "--", "generate"]) == 1
    assert signal.getsignal(signal.SIGTERM) is previous
    if missing == "server":
        assert harness.processes == []
    else:
        assert len(harness.processes) == 1
        assert_stopped(harness)


@pytest.mark.parametrize("operation", ["import", "help", "root-help"])
def test_import_and_help_do_not_import_vllm_or_start_processes(
    operation: str, tmp_path: Path
) -> None:
    code = """
import importlib
import sys

operation = sys.argv[1]

def guard(event, args):
    if event == "import" and args[0].split(".")[0] in {"vllm", "httpx"}:
        raise AssertionError(f"Unexpected dependency: {args[0]}")
    if event == "import" and operation == "root-help":
        assert args[0] != "agentinstruct.integrations.vllm.serve"
    if event.startswith("socket.") or event == "subprocess.Popen":
        raise AssertionError(f"Unexpected startup effect: {event}")

sys.addaudithook(guard)
if operation == "import":
    importlib.import_module("agentinstruct.integrations.vllm.serve")
else:
    from agentinstruct.cli import main
    try:
        main(["--help"] if operation == "root-help" else ["vllm", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
"""
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code, operation],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    if operation == "help":
        assert "usage: agentinstruct vllm" in result.stdout
        assert "--server-python" in result.stdout
    elif operation == "root-help":
        assert "Start a local vLLM server and run a program" in result.stdout
    else:
        assert result.stdout == ""
