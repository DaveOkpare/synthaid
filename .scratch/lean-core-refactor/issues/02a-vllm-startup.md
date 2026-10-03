# 02a: Start a local vLLM server at program boot

Type: implementation
Status: resolved
Blocked by: 02

Authorized by the user's 2026-10-01 request to launch the server through Python if available, or a startup script otherwise. This is a separate small startup slice; Task 03's provider/conformance changes remain unstarted.

## Description

Provide an optional repository launcher outside the shipped core. Python starts the official `vllm.entrypoints.cli.main serve` entrypoint in a child process, which uses the same dispatch as `vllm serve`. It waits for readiness, runs a supplied Python or CLI program, and stops only the processes it started. The provider remains a base-URL HTTP client.

Direct `run_server(args)` exists but requires vLLM's argument parser, event loop, and signal lifecycle. Using the official entrypoint in a dedicated child preserves Python-controlled startup without embedding those dependencies into agentinstruct.

## Acceptance criteria

- [x] No vLLM imports/dependency or startup effects are added to the library core or ordinary validation/import paths.
- [x] A small context manager and script launch once on explicit use, wait for local `/health` with a deadline, and run generation only after readiness.
- [x] Missing interpreter/vLLM, early server exit, timeout, command failure, and interruption leave no owned server/client processes running; cleanup targets their own process groups.
- [x] The script accepts a model and optional server interpreter/options, exposes the matching base URL, and invokes commands without a shell.
- [x] Tests use fake processes and HTTP transports; no model download or real inference is performed. Document a concrete boot command and Python usage.

## Verification

Focused lifecycle/startup tests, CLI help, lint/format and strict typing. Verify startup/collection safety and existing generation tests. Count the launcher separately from shipped core code. No live launch is authorized without an actual model/environment selection.

## Likely files

`scripts/run_with_vllm.py`, `tests/test_vllm_startup.py`, and a short README startup section. Update this ticket/work index after verification.

## Sources

- [Official server usage](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/)
- [Python CLI entrypoint](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/cli/main.py)
- [Serve dispatch](https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/cli/serve.py)

## Answer

Completed on 2026-10-01. `scripts/run_with_vllm.py` provides `vllm_server()` and a CLI wrapper. It starts the official Python `serve` entrypoint once in a separate process, waits for `/health`, yields the base URL or starts the supplied program, and cleans up its owned process groups. It accepts a separate server interpreter and normal vLLM flags. A finite readiness deadline, occupied-port rejection, child-death checks, and shell-free argv protect startup behavior. Server logs use stderr; the program retains stdout and exit status. Direct Python usage runs from the main thread and temporarily handles/restores SIGTERM.

An implementation agent and a test agent reviewed their own work. Independent review found a SIGTERM leak in direct Python context usage; it was fixed and locked by readiness/body interruption and handler-restoration tests. Re-review reported no remaining actionable findings.

Verification: **21 startup tests**, **30 startup/import-safety tests**, and the final full suite **578 passed**. Whole-repository Ruff lint/format, project strict mypy (58 source files), explicit strict typing of the launcher, offline CLI help, lock check, wheel/sdist build, and diff checks passed. The archive inspection confirmed no vLLM requirement, launcher inclusion, or scratch/task/run artifacts in the wheel. The README records shell and Python usage.

Size/scope: **163 repository launcher lines**, outside the wheel; shipped core/integration source remains **9,497 lines** from Task 02. No production library or Task Package interface changed in this slice. Task 03's removal of the conformance/provider subsystem remains unstarted.

Tests mocked processes, port probes, and HTTP responses. No real vLLM environment, model download, or inference was started; actual use requires the caller's installed vLLM interpreter and model. The launcher targets a local POSIX server; callers with an existing local/remote server use their configured base URL directly.
