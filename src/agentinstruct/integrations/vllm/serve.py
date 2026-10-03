"""Start a local vLLM server, run a program after readiness, and stop both."""

from __future__ import annotations

import argparse
import math
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from types import FrameType
from typing import Any


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Reap the child and terminate any descendants in its private session."""
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=5)
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=5)


@contextmanager
def vllm_server(
    model: str,
    *,
    port: int = 8000,
    python: str = sys.executable,
    server_args: Sequence[str] = (),
    startup_timeout: float = 600.0,
) -> Iterator[str]:
    """Yield a ready local server, restoring signals and stopping its process group."""
    _validate_server(model, port, server_args, startup_timeout)
    command = _server_command(model, port, python, server_args)
    with _termination_signals(), _server_process(command) as process:
        _wait_ready(process, port, startup_timeout)
        yield f"http://127.0.0.1:{port}/v1"


class _Terminated(SystemExit):
    def __init__(self) -> None:
        super().__init__(128 + signal.SIGTERM)


def _on_sigterm(_signal: int, _frame: FrameType | None) -> None:
    raise _Terminated


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.program[:1] == ["--"]:
        args.program = args.program[1:]
    if not args.program:
        parser.error("a program is required after --")
    return _cli_server(args)


def _validate_server(
    model: str, port: int, options: Sequence[str], timeout: float
) -> None:
    if not model.strip():
        raise ValueError("A model is required")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer between 1 and 65535")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Startup timeout must be finite and positive")
    if any(arg.split("=", 1)[0] in {"--host", "--port"} for arg in options):
        raise ValueError("Use port= for the port; the server host is 127.0.0.1")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"Cannot use local port {port}: {error}") from error


@contextmanager
def _termination_signals() -> Iterator[None]:
    previous = signal.signal(signal.SIGTERM, _on_sigterm)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextmanager
def _server_process(command: Sequence[str]) -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen(command, stdout=sys.stderr, start_new_session=True)
    try:
        yield process
    finally:
        _stop(process)


def _wait_ready(process: subprocess.Popen[bytes], port: int, timeout: float) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=1.0, trust_env=False) as client:
        while True:
            remaining = _remaining(process, deadline)
            ready = _healthy(client, port, remaining)
            remaining = _remaining(process, deadline)
            if ready:
                return
            time.sleep(min(0.25, remaining))


def _remaining(process: subprocess.Popen[bytes], deadline: float) -> float:
    if process.poll() is not None:
        raise RuntimeError(
            f"vLLM exited before readiness (status {process.returncode}); "
            "check server logs and its Python environment"
        )
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("vLLM was not ready within the startup timeout")
    return remaining


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentinstruct vllm", description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--server-python", default=sys.executable)
    parser.add_argument("--server-args", default="", help="Quoted vLLM serve options")
    parser.add_argument("--startup-timeout", type=float, default=600.0)
    parser.add_argument("program", nargs=argparse.REMAINDER)
    return parser


def _cli_server(args: argparse.Namespace) -> int:
    try:
        options = dict(
            port=args.port,
            python=args.server_python,
            server_args=shlex.split(args.server_args),
            startup_timeout=args.startup_timeout,
        )
        with vllm_server(args.model, **options) as url:
            print(f"vLLM ready: {url}", file=sys.stderr)
            return _program_status(args.program)
    except KeyboardInterrupt:
        return 130
    except _Terminated:
        return 128 + signal.SIGTERM
    except (OSError, RuntimeError, ValueError) as error:
        print(f"agentinstruct vllm: {error}", file=sys.stderr)
        return 1


def _server_command(
    model: str, port: int, python: str, options: Sequence[str]
) -> list[str]:
    return [
        python,
        "-m",
        "vllm.entrypoints.cli.main",
        "serve",
        model,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        *options,
    ]


def _healthy(client: Any, port: int, remaining: float) -> bool:
    import httpx

    try:
        response = client.get(
            f"http://127.0.0.1:{port}/health", timeout=min(1.0, remaining)
        )
        return bool(response.status_code == 200)
    except httpx.HTTPError:
        return False


def _program_status(program: Sequence[str]) -> int:
    process = subprocess.Popen(program, start_new_session=True)
    try:
        returncode = process.wait()
        return returncode if returncode >= 0 else 128 - returncode
    finally:
        _stop(process)


if __name__ == "__main__":
    raise SystemExit(main())
