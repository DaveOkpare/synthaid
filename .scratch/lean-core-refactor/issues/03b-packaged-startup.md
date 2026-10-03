# 03b: Package the optional vLLM startup launcher

Type: implementation
Status: resolved
Blocked by: 02a

## Description

Move the launcher to `integrations/vllm/serve.py`, remove the repository script, and expose `agentinstruct vllm --model MODEL -- PROGRAM ...`. Preserve readiness, bounded deadlines, process cleanup, exit status, and import safety. No vLLM engine dependency or import.

## Scope

Three logical units: launcher relocation and integration docstrings; lazy CLI dispatch; startup behavior tests.

## Verification

Existing lifecycle tests and real short-command help, self-review, then root package-content checks.

## Answer

Resolved 2026-10-02. Moved the 163-line repository launcher into `src/agentinstruct/integrations/vllm/serve.py` and removed the script path. `agentinstruct vllm --model MODEL -- PROGRAM ...` dispatches lazily through the existing entry point. Root help lists the command; command help uses the short name. Ordinary help/validation/generation do not import the launcher.

Readiness deadlines, owned process-group cleanup, SIGTERM/interrupt handling, argument boundaries, and child exit statuses are preserved. The main-thread Python helper remains available at the packaged module path. vLLM stays installed only in the selected server interpreter; no inference-engine dependency or import is added. This optional launcher uses POSIX process groups.

Startup suite expanded from 21 to 22 tests; startup/CLI/offline-release checks pass 50 tests. The implementing agent reviewed its changes. Real short-command help and built-wheel import/contents pass; final aggregate gates are in the parent answer. Relocation is counted separately from deletion.
