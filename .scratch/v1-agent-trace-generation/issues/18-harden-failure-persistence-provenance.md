# 18: Harden failure persistence and provenance

**What to build:** Ensure failures at every lifecycle boundary retain the most complete safe Trace possible, clean up resources, preserve causes, and never expose secrets or invent successful data.

**Blocked by:** 11 — Complete Seed sources and package safety; 14 — Add Responses API parity and private reasoning; 16 — Load custom components through explicit references

**Status:** resolved

**Type:** implementation

- [x] Configuration, Seed, template, Provider, Agent, Reviewer, Tool, Environment, Runtime, persistence, and Verifier failures are classified at the narrowest recoverable boundary.
- [x] Failure records include lifecycle stage, Agent, Task Step, proposal or revision attempt, timestamp, and chained cause where available.
- [x] Accepted Messages committed before a later failure remain durable and ordered; rejected proposals remain Events.
- [x] Environment and Provider cleanup runs after success, truncation, cancellation, timeout, and failure.
- [x] A Run-wide source failure stops the Run, while a Trace-specific failure permits later Seeds unless fail-fast is active.
- [x] Credentials, secret headers, and resolved secret values are absent from persisted plans, metadata, errors, and diagnostic output.
- [x] Trace snapshots are made durable before their Run index references become visible.
- [x] No automatic infrastructure retry obscures call counts, timing, cost, or partial effects.


## Answer

Implemented narrow Agent/proposal, review, Tool, Environment, Provider, storage
and Verifier failure evidence with lifecycle identity, available actor/Step/turn,
proposal/revision counters, safe bounded causes and timestamps. Malformed actions
are distinct from Agent execution failures. Earlier accepted Messages and rejected
Events remain in failed snapshots; subsequent queued Messages start their own
review budgets. Existing package/Seed/template and source-wide classifications
remain intact, with no infrastructure retries.

External cancellation now finalizes Environments, closes every constructed
Provider and preserves a failed sealed Trace plus Run index/manifest before
propagating when storage permits. Repeated cancellation cannot interrupt cleanup;
configured generation/verification timeouts bound cleanup without adding a global
timeout. Reverification appends an unverified cancellation attempt and preserves
prior valid decisions and immutable generation files. Recording/cleanup failures
do not skip remaining resources, and persistence failures stop Seed advancement.

Runtime-only diagnostics redact configured credential values, including metadata
keys and Seed identities, and secret diagnostic headers. Accepted redacted
Messages are returned to Interaction so relay and Tool effects use the exact
committed values. RunResult/index identities match their safe snapshots for valid
and invalid Seeds; authored non-secret Task/Seed values remain intact. Direct
Provider Plans share safe URL/environment-reference validation. Strict JSON rejects
non-string object keys, non-finite numbers, cycles and unsupported argument values;
Agent Tool JSON rejects duplicate keys and non-finite values.

Source files and nested directories, empty journals/artifact directories, terminal
snapshots and verification directories are synced before Run discovery references.
OS-boundary failure fixtures demonstrate that failed sync prevents inference/index
publication and that later journal failure still preserves the accepted partial
snapshot where storage is writable. No unsealed Trace is indexed.

Validation: all 432 affected tests passed across hardening (38 cases), Runner,
Tools, review, verification, components, collections, Seed/package safety, Steps,
dialogue, inspection, model quality, Providers, Responses, import safety and CLI.
Strict mypy passed (50 source files), Ruff lint and format passed, and
`git diff --check` passed. Existing tests now select the more precise `agent_error`
Events. Compatible endpoint Verifier sidecars retain strict profile validation
through JSON round-tripping. Full-suite/build and release integration remain
reserved for ticket 19; no live model call or vLLM conformance claim was made.


Review corrections: safe proposal normalization now precedes Reviewer approval and
Tool-result normalization precedes output-schema validation. Persistence rejects
an unsanitized Message Commit instead of modifying previously approved/validated
evidence. Public Runner regressions prove Reviewer-visible Messages and arguments
exactly match committed Messages and executed arguments, and a redacted result
that violates its output schema is never committed. Malformed original Message
checks and the existing committed relay regression remain intact.

Diagnostic redaction now consumes complete single-/double-quoted credential
values in dictionary, JSON and header text, including escaped quotes and spaces,
for both top-level failures and chained causes. Authored non-secret data still
uses the separate non-diagnostic path. All six added regressions reproduced the
review findings before the fixes; all 44 hardening cases and 340 affected tests
now pass. Strict mypy (50 source files), Ruff lint/format (119 files), and
`git diff --check` pass. The correction remains unstaged for the parent review.
