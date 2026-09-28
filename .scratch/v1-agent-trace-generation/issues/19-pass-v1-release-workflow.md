# 19: Pass the complete V1 release workflow

**What to build:** Demonstrate that the assembled framework can produce a verified, inspectable, exportable Dataset from a representative multi-Seed, multi-step, Tool-using dialogue and satisfy every repository release gate.

**Blocked by:** 15 — Add tested vLLM Provider profiles; 17 — Inspect recorded Runs and Traces; 18 — Harden failure persistence and provenance

**Status:** resolved

**Type:** implementation

- [x] One deterministic end-to-end fixture runs multiple Seeds through a multi-step user–assistant dialogue with one Target Agent.
- [x] The fixture includes a rejected and revised conversational Message, a rejected Tool call that never executes, an accepted private Tool exchange, and retained cross-step history.
- [x] The Run contains accepted, rejected, unverified, invalid, or failed examples sufficient to prove status accounting and explicit export inclusion rules.
- [x] Final Verification, reverification, native export, accepted-only OpenAI JSONL export, static inspection, and TUI inspection all operate on persisted Trace snapshots.
- [x] The public asynchronous API, synchronous wrapper, and CLI commands share one lifecycle and produce consistent results.
- [x] Importing the package and collecting tests perform no network access, model initialization, or storage mutation.
- [x] Locked dependency validation, Ruff lint, Ruff format checking, the deterministic pytest suite, CLI smoke tests, and source/wheel building all pass.
- [x] User-facing documentation explains the first successful validate, run, inspect, export, and reverify workflow without promising out-of-scope features.


## Answer

The `examples/release-workflow` Task Package now exercises the full public
lifecycle without inference clients. Its default two Seeds both reach accepted
Verification with fresh Agent/Tool state. The six-record coverage source adds
rejected, unverified, invalid and failed attempts. Both accepted dialogues retain
history across `collect` and `conclude`, reject/revise conversational drafts and
Tool proposals, execute only the accepted private target Tool, and finish through
reviewed Step controls. Persisted assertions cover rejected Events, private
participant projection, independent Tool invocation counts, all status counts,
append-only reverification, native/OpenAI exports, Inspector/static/TUI views,
`Runner.run`, `generate_sync`, and installed CLI commands.

Both exporters now accept Run directories alongside existing ordered Trace inputs,
using `load_run`'s confined relative discovery. Optional `run_ids`, `trace_ids`,
`seed_ids` and status sets select current `load_trace` decisions; an explicit
Verification ID can select a historical valid attempt. The CLI exposes repeatable
`--run-id`, `--trace-id`, `--seed-id` selectors. All original input Run roots remain
protected from output overwrite even when empty or filtered to zero records.
Tool arguments remain structured Dataset JSON, with stringification confined to
Provider wire adapters.

The separate collection audit permits HTTPX transport class imports, disables
pytest caching/log files and interpreter bytecode writes, blocks network/storage
operations and HTTP client construction, and observes public model Agent/Provider
constructor entry even when inherited/lazy. A deliberately constructed lazy
Provider proves the guard detects model initialization. The existing stricter
production import/help/version/validation audit is unchanged. Default test network
boundaries also block live calls regardless of ambient credentials.

README now documents a first successful validate/run/inspect/export/reverify flow,
current selectors, component and Seed-source support, and both structured-output
API surfaces. Obsolete staged promises about Steps, Tools, judges and vLLM were
removed. No live vLLM endpoint was supplied, so the pinned candidate remains
explicitly unverified; no live compatibility claim or GPU provisioning occurred.

Release gates used `UV_CACHE_DIR=/tmp/agentinstruct-uv-cache` and
`/Users/davidokpare/.local/bin/uv`:

- `uv lock --check`: resolved 46 packages; passed.
- `uv sync --locked`: resolved 46 / checked 45 packages; passed.
- `uv run --locked ruff check .`: all checks passed.
- `uv run --locked ruff format --check .`: 130 files already formatted.
- `uv run --locked mypy`: no issues in 52 source files.
- `uv run --locked pytest -q`: **552 passed in 48.68s**, one final full deterministic run.
- CLI smokes: **12 passed**, covering help/version, validation, default generation,
  static/JSON/TUI inspection, both exports, Seed selection, reverification, and the
  expected exit 1 plus all six retained attempts for the deliberate coverage Run.
- `uv build --out-dir /tmp/agentinstruct-v1-release.0JUgIP/dist`: source and wheel
  succeeded, rebuilt after the final README correction.
- Distribution audit: wheel has 36 entries and source archive has 33 files; both
  include all 30 package files and `py.typed`. Neither includes Runs, credentials,
  caches, environments, tests, research or prototypes.
- `git diff --check`: passed.

Build artifacts:
`/tmp/agentinstruct-v1-release.0JUgIP/dist/agentinstruct-0.1.0-py3-none-any.whl`
(SHA-256 `63fd466707987a11cbb4428db65ad02ffa89fb27e4d8c4abac180a4c38f5e85d`)
and `/tmp/agentinstruct-v1-release.0JUgIP/dist/agentinstruct-0.1.0.tar.gz`
(SHA-256 `a94c96a213622c1d5de33e1b7712f3bfd007c9afd280cffd9df55be69063fd68`).
CLI and archive audit reports are retained beside them in `cli-smokes.json` and
`distribution-audit.json`; smoke Runs and Datasets are confined to that `/tmp`
directory. Independent Spec and Standards reviews completed with no actionable
findings.
