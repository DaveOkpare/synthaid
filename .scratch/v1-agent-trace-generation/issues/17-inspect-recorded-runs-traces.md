# 17: Inspect recorded Runs and Traces

**What to build:** Let an operator understand recorded Runs and Traces without loading transient Runner state or mutating generation artifacts.

**Blocked by:** 09 — Retain history across Task Steps; 10 — Run deterministic JSON and JSONL Seed collections; 14 — Add Responses API parity and private reasoning

**Status:** resolved

**Type:** implementation

- [x] The inspect command renders a concise non-interactive Run or Trace summary from persisted data.
- [x] A simple terminal UI can navigate accepted Conversation, participant projections, private Tool activity, review attempts, Verification attempts, provenance, failures, and artifacts.
- [x] Task Step boundaries and review-exhausted Messages are visible.
- [x] Reasoning presence and retention policy are visible without exposing suppressed reasoning text.
- [x] Collection summaries report ordered Trace references and counts for invalid, failed, unverified, rejected, and accepted statuses.
- [x] Inspection does not rewrite, reverify, resume, or otherwise mutate the selected Run or Trace.
- [x] Rendering and navigation are tested against recorded fixtures without pixel-level snapshots.

## Answer

Added the persisted-only `Inspector`, immutable `RecordedRun`/`RecordedTrace`, and
reusable `load_run` discovery API. Run discovery preserves relative index order,
supports moved Runs, and checks confinement of snapshots/Verification sidecars and
Run/Trace/Seed identity. Current counts derive from canonical `load_trace` decisions;
historical index counts and the original manifest remain separately labelled.
Invalid Seed attempts with no compiled Plan, empty Runs, source failures and
standalone snapshots are supported. Latest failed Verification attempts remain
visible alongside the earlier selected valid decision.

`inspect` provides concise static summaries, JSON views, Trace selection and a
small paginated terminal UI without new dependencies. Operator views show accepted
Conversation, Tool activity, review attempts, Verification, provenance, failures,
artifacts and reasoning. Participant projections retain shared accepted Messages
and only the participant's private Tools. Task Step boundaries and review-exhausted
Messages remain visible. Reasoning presence, declared retention and suppression
cover both generation Events and Verification-attempt Events. Recorded terminal
controls are escaped; inspection never invokes components or mutates evidence.
See [inspection commands and navigation](../../../README.md#inspect-recorded-runs-and-traces).

Initial validation: 16 new public inspection/CLI/navigation cases use persisted Runner
fixtures, deterministic Provider transports and byte-preservation assertions. A
subprocess additionally forbids filesystem writes, network calls and SDK imports
during CLI inspection. The 195 affected inspection, CLI, import-safety, collection,
Verification, Step, review and Responses tests pass. Strict mypy, Ruff lint/format
and `git diff --check` pass. No live calls, full-suite run or build was performed;
the final release workflow remains ticket 19.

Review follow-up: reasoning inspection also reads response evidence nested inside
Provider structured-output errors. Invalid JSON and schema-mismatch Verifier calls
remain visible with usage, request identity and the declared retention behavior;
one Event is counted once when direct and nested evidence coexist. Four additional
Runner/fake-transport cases exercise both failures with retention enabled/disabled,
plus standalone native fixtures exercise duplicate evidence. All 71 focused
inspection, Responses and model-quality tests pass, as do strict mypy, Ruff
lint/format and `git diff --check`.
