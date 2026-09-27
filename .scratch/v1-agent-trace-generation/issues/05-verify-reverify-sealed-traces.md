# 05: Verify and reverify sealed Traces

**What to build:** Let a dataset producer evaluate a sealed Trace with weighted Boolean Criteria, derive its quality status, export accepted data by default, and append later Verification attempts without regenerating the Conversation.

**Blocked by:** 03 — Generate one deterministic single-agent Trace

**Status:** resolved

**Type:** implementation

- [x] Deterministic code Verifiers and LLM-judge-shaped fakes implement one asynchronous protocol over an immutable Trace snapshot.
- [x] Each declared Criterion has a unique identifier and positive finite weight, and the framework computes passing weight divided by total weight.
- [x] A valid score at or above the inclusive threshold produces accepted status; a lower valid score produces rejected status.
- [x] Missing, duplicate, unknown, or non-Boolean verdicts and Verifier execution failures produce unverified status rather than false Criteria.
- [x] Each Verification attempt is immutable and versioned, and reverification does not change accepted Conversation bytes.
- [x] Default OpenAI-style export includes only accepted Traces; other terminal statuses require explicit inclusion.
- [x] Reviewer and Verifier scoring logic is shared where appropriate without merging their lifecycle responsibilities.

## Answer

Implemented final Verification and append-only reverification at the agreed Runner,
persisted snapshot, Dataset export, and CLI seams. `Criterion`, `Rubric`, and
strict weighted Boolean scoring live in the independent `quality` module for
ticket 06 reuse; no Reviewer lifecycle was added. Task Packages validate and
snapshot `verifier/rubric.toml`, then persist a complete immutable `VerifierPlan`.

`Verifier.verify` consumes the finalized, durably sealed `TraceSnapshot`.
The built-in `DeterministicVerifier` and protocol-faithful judge-shaped test
extensions use the same asynchronous boundary. Invalid results, exceptions, and
timeouts produce an unverified attempt with error evidence and no fabricated
false Criteria. Attempt records include schema version, sequence, unique ID,
Trace identity, full policy, component provenance, verdicts, feedback, and timing.

`reverify` appends an atomically published attempt without replacing existing
attempts or any generation file. Sealed Interactions also reject further turns.
`load_trace` merges embedded native evidence with sidecar attempts, preserves
identical copies, and derives eligibility from the latest valid attempt or an
explicitly selected valid ID. A later invalid attempt cannot erase a prior valid
decision, and failed or invalid generation cannot be promoted by verification.
Standalone native snapshots keep sidecars scoped to their filename (for example,
`a.json.verification/`); canonical `trace.json` snapshots and Trace directories
retain the existing `verification/` layout. Two separately exported snapshots in
one archive can therefore be independently reverified, loaded, and exported.
Embedded evidence and sidecars both reject foreign Trace identities and
conflicting copies of the same immutable attempt; identical copies deduplicate.
The export CLI exposes selection with `--verification`; `reverify --package`
can apply a replacement policy. The [verified example](../../../examples/verified-single/task.toml)
and [usage guide](../../../README.md#verify-and-reverify-traces) demonstrate offline use.

Validation used `UV_CACHE_DIR=/tmp/agentinstruct-uv-cache`:

- `uv run pytest tests/test_cli.py tests/test_verification.py -q`: **51 passed**,
  including red-to-green regressions for neighboring standalone snapshots,
  a standalone snapshot beside canonical `trace.json`, and invalid embedded
  evidence. The neighboring snapshots retain independent attempt sequences,
  export decisions, byte-identical native snapshots, and unchanged Conversations.
- Earlier focused Runner/sealing check, `uv run pytest tests/test_verification.py tests/test_runner.py -q`: **32 passed** at that slice.
- `uv run mypy`: **success**, 17 source files.
- `uv run ruff check .`: **passed**; `uv run ruff format --check .`: **55 files already formatted**.
- `git diff --check`: **passed**.
- Installed CLI smoke using `examples/verified-single`: one accepted Trace,
  accepted reverification at sequence 2, one default-exported record, and
  byte-identical Conversation before and after reverification.

Provider-backed judges remain ticket 13 work, and custom Verifiers currently use
an explicit library factory. Reverification leaves original Run counts unchanged;
the complete Trace snapshot supplies current eligibility. Full-suite/build checks
and independent Standards/Spec reviews are handled by the parent before commit.
