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
    """Yield a ready base URL from the main thread, then stop the owned server."""
    if not model.strip():
        raise ValueError("A model is required")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer between 1 and 65535")
    if not math.isfinite(startup_timeout) or startup_timeout <= 0:
        raise ValueError("Startup timeout must be finite and positive")
    if any(arg.split("=", 1)[0] in {"--host", "--port"} for arg in server_args):
        raise ValueError("Use port= for the port; the server host is 127.0.0.1")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"Cannot use local port {port}: {error}") from error

    import httpx

    base_url = f"http://127.0.0.1:{port}/v1"
    previous = signal.signal(signal.SIGTERM, _on_sigterm)
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            [
                python,
                "-m",
                "vllm.entrypoints.cli.main",
                "serve",
                model,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                *server_args,
            ],
            stdout=sys.stderr,
            start_new_session=True,
        )
        deadline = time.monotonic() + startup_timeout
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            while True:
                if process.poll() is not None:
                    raise RuntimeError(
                        f"vLLM exited before readiness (status {process.returncode}); "
                        "check server logs and its Python environment"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"vLLM was not ready within {startup_timeout}s")
                try:
                    response = client.get(
                        f"http://127.0.0.1:{port}/health", timeout=min(1.0, remaining)
                    )
                    ready = response.status_code == 200
                except httpx.HTTPError:
                    ready = False
                if process.poll() is not None:
                    raise RuntimeError(
                        f"vLLM exited during readiness (status {process.returncode})"
                    )
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"vLLM was not ready within {startup_timeout}s")
                if ready:
                    break
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.25, remaining))
        yield base_url
    finally:
        try:
            if process is not None:
                _stop(process)
        finally:
            signal.signal(signal.SIGTERM, previous)


class _Terminated(SystemExit):
    def __init__(self) -> None:
        super().__init__(128 + signal.SIGTERM)


def _on_sigterm(_signal: int, _frame: FrameType | None) -> None:
    raise _Terminated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentinstruct vllm", description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--server-python", default=sys.executable)
    parser.add_argument("--server-args", default="", help="Quoted vLLM serve options")
    parser.add_argument("--startup-timeout", type=float, default=600.0)
    parser.add_argument("program", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.program
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a program is required after --")

    try:
        with vllm_server(
            args.model,
            port=args.port,
            python=args.server_python,
            server_args=shlex.split(args.server_args),
            startup_timeout=args.startup_timeout,
        ) as base_url:
            print(f"vLLM ready: {base_url}", file=sys.stderr)
            process = subprocess.Popen(command, start_new_session=True)
            try:
                returncode = process.wait()
                return returncode if returncode >= 0 else 128 - returncode
            finally:
                _stop(process)
    except KeyboardInterrupt:
        return 130
    except _Terminated:
        return 128 + signal.SIGTERM
    except (OSError, RuntimeError, ValueError) as error:
        print(f"agentinstruct vllm: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
