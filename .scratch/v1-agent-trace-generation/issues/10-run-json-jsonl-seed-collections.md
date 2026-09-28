# 10: Run deterministic JSON and JSONL Seed collections

**What to build:** Let an operator run a Task over every Seed in a JSON or JSONL source and receive one isolated, indexed Trace per Seed with deterministic ordering and collection-level status counts.

**Blocked by:** 03 — Generate one deterministic single-agent Trace; 05 — Verify and reverify sealed Traces

**Status:** resolved

**Type:** implementation

- [x] A JSON object yields one Seed, a JSON array yields one Seed per element, and JSONL yields one Seed per non-empty record.
- [x] Seed enumeration order is deterministic and each valid Seed compiles to an independent immutable Run Plan.
- [x] A configured Variable may supply a stable Seed ID; otherwise a canonical content hash supplies it.
- [x] Duplicate Seed IDs within one Run are rejected without conflating Seed identity and Trace-attempt identity.
- [x] Invalid, failed, unverified, rejected, and accepted attempts are represented in the Run index and aggregate counts.
- [x] A Seed-specific failure does not stop later Seeds by default, while fail-fast stops after the first qualifying failure.
- [x] Each Trace is durably finalized before the Runner advances to the next Seed.
- [x] No accepted history or trace-bound mutable state leaks between Seeds.

## Answer

One `Runner.run(TaskPackage)` invocation now enumerates JSON objects, JSON array
elements, or nonempty JSONL lines in source order. Array positions and physical
JSONL line numbers are one-based. Source enumeration yields immutable records
before identity binding and compilation, providing a boundary for ticket 11's
additional source forms. Each valid record compiles independently through the
existing shared template helpers. A configured Variable supplies its string or
integer ID, otherwise canonical content hashing supplies it. IDs remain stable
across Runs and JSON object-key ordering; duplicate IDs within a Run produce
separate invalid Trace attempts. IDs are reserved even when later compilation
fails, and all attempts retain fresh Trace IDs.

The Runner durably seals each generation snapshot, appends any Verification
sidecar, and publishes exactly one index entry before requesting the next Seed.
Index publication also syncs new Trace/verification directory entries. Run
finalization updates the manifest without appending the index again. All five
terminal statuses contribute to ordered references and counts. Every Trace gets
fresh Agent, Interaction, Reviewer, Tool, Environment, Verifier, recorder, and
Task Step progress; accepted/private history and revision feedback remain scoped
to their Trace. Existing review-before-effects and completion behavior is retained.

Malformed JSONL lines, invalid array elements, duplicate IDs, Variable failures,
and rendering failures remain indexed invalid attempts and do not stop later
Seeds. An invalid standalone snapshot retains explicit Task identity/digest and
`seed_record` data, origin, digest, raw malformed text when applicable, and failure
Events. Its `run_plan` is empty and no executable Plan file is fabricated. Native
export includes these records when selected; OpenAI export excludes their empty
Conversations. Syntax or source-enumeration failures mark the Run failed and retain
previously available attempts plus a manifest diagnostic. If storage cannot publish
the required terminal snapshot/index pair, the Run stops with its available durable
references and diagnostic where storage remains writable.

`fail_fast=True` and CLI `--fail-fast` stop after `invalid` or `failed` attempts,
as specified by ADR-0003; ordinary `unverified` and `rejected` outcomes continue.
`generate` and `generate_sync` forward the same option and Seed-source override.
Run Results expose `finished`, `stopped`, or `failed` invocation status plus an
optional source/storage error. The CLI exits 1 for invalid/failed attempts or a
failed Run, 2 for package-wide validation failure, and 0 for completed quality
outcomes. Package-wide validation remains before Run creation.

`TaskPackage.validate()` and the thin `validate` CLI use the same collection
compiler without components or Run output. Reports include all compiled Plans,
ordered record diagnostics, valid/invalid counts, and any source error. The
existing single-valid-record `plan` output and `TaskPackage.compile()` one-record
API remain available.

Evidence:

- Red/green Runner and CLI slices cover per-Trace durability observed from the
  next Seed's Agent, mixed outcomes, stable/duplicate IDs, malformed records,
  source syntax failure after prior attempts, fail-fast qualification, model-free
  collection validation, and storage failure that prevents safe advancement.
- `uv run --locked pytest tests/test_collections.py tests/test_cli.py
  tests/test_runner.py tests/test_steps.py tests/test_review.py tests/test_tools.py
  tests/test_verification.py tests/test_dialogue.py -q`: **206 passed**, including
  **16 collection cases**. The freshness scenario exercises reviewed private
  multi-Tool calls, revision feedback, two Task Steps, and final Verification.
- `uv run --locked mypy`: success for 26 source files. Ruff lint, Ruff format
  check, and `git diff --check` pass.
- `uv run --locked agentinstruct validate examples/seed-collection --json`:
  **2 valid records** without generation.
- `uv run --locked agentinstruct run examples/seed-collection --output
  /tmp/agentinstruct-ticket10-jsonl --json`: **2 accepted Traces**. The equivalent
  `--seed examples/seed-collection/seeds.json --fail-fast` Run also accepts both.

See [collection usage](../../../README.md#run-a-seed-collection) and the
[offline example](../../../examples/seed-collection/task.toml). CSV, directory
sources, Python iterables, Seed JSON Schema validation, and the remaining package
safety work belong to ticket 11. Parent review owns the commit; the full-suite
and build verification follows ticket 19.

### Standards review follow-up

`Seed.__post_init__` now defensively copies and recursively freezes its data,
including mappings nested inside arrays. Public `compile_seed()` therefore
cannot retain mutable caller-owned input through a supplied Seed. The compiler
regression mutates the original top-level and nested dictionaries after
compilation and requires unchanged Seed data, Variables, instruction, serialized
Plan, and Plan digest. The regression failed before the fix.

`uv run --locked pytest tests/test_collections.py tests/test_runner.py
tests/test_cli.py -q`: **43 passed**. Strict mypy, Ruff lint/format checks, and
`git diff --check` passed. This follow-up remains unstaged for parent rereview;
no full suite or commit was run.
