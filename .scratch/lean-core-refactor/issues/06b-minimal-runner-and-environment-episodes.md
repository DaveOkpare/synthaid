# 06b: Minimal Runner and Environment-owned Episodes

Type: implementation
Status: resolved
Blocked by: 06a
Date: 2026-10-03

Implement [ADR-0012](../../../docs/adr/0012-keep-runner-as-an-environment-task-loop.md),
including the user's clarification that Environment runs final Verification.
Runner takes one Environment and prepared task records, loops and calls it.
Environment creates one fresh Episode for a whole multi-round conversation,
then seals it and invokes optional final Verification. Agent keeps its own Review.

## Ordered scope

1. Give Environment `run(task) -> Episode` and the overridable
   `conversation(episode)` method; keep actual execution safeguards on their
   owners and provide real Environment resource cleanup.
2. Replace Runner with the ordinary task loop returning Episodes. Remove all
   Run bookkeeping, copied state, preparation flags, storage/Verifier options,
   cleanup branches and task-file imports.
3. Keep file preparation and RunResult/manifest/index behavior in the optional
   task-file adapter. Bind actual dependencies onto Environment; retire
   prepared Environment/task/Verifier tuples. CLI calls that adapter directly.
4. Migrate active callers and behavioral tests to the actual owners; run full
   offline checks and independent review. Publish actual source changes and
   stop for user code review before later unrelated tickets.

## Constraints and verification

No new runtime owner, Plan, context, pipeline, factory, compatibility aliases or
state containers. All changed/new functions are at most 20 inclusive physical
lines, with readable formatting. Keep existing Episode recording behavior in
this slice; do not add a speculative memory-only mode or grading pipeline.

Preserve actual review-before-effect, private histories, accepted intent before
Tool execution, JSON/schema checks, credential redaction, independent Episode
state, partial history, deadlines, cancellation sealing/propagation, attempted
cleanup, immutable generation and append-only final grading. Verifier/Provider
resources stay available across all tasks until Environment closes. No Runner
resource reclamation or Run-level publication remains.

Latest direction retires the previous Runner storage/Verifier/fail_fast API and
automatic cleanup contract. Existing task files and CLI output stay supported.
Tests of retired Runner ownership move to Environment or adapter; no safety
assertion is deleted solely to pass. Environment close failures propagate at
context exit without rewriting previously sealed generation.

Baseline: 334 passing tests, 7,396 shipped Python lines, 28 files, 95 classes,
49 exports; runner.py 454 lines/32 definitions. Saved source and test baselines
under /private/tmp. Retain the cumulative uncommitted worktree; no Git writes.

Gates: focused increment tests; full deterministic pytest, strict mypy, Ruff,
format, lock check, wheel/sdist build; built-wheel adapter and actual retail
example smoke; source-byte/package checks and changed-function length audit.

## Answer

Implemented ADR-0012. Runner now has only initialization and the ordinary task
loop: 23 lines and two methods, down from 454 lines and 32 definitions. It accepts
one Environment and tasks and returns Episodes without preparation, persistence,
final Verification, error handling or automatic resource cleanup.

Environment is initialized with actual Agents and an optional Verifier. Its
run(task) creates one fresh Episode, executes the full conversation, seals
generation and invokes final Verification. Dialogue supports multiple rounds;
the six-message regression checks per-Agent Review and one whole-Episode grade.
Applications close resources with async with environment after all tasks.

The optional TaskPackage adapter retains task files, loading/parsing, rendering,
segments, source snapshots, invalid inputs, RunResult, manifests, indexes and
fail_fast. Async preparation binds actual owners and cleans up partial bindings.
CLI calls the adapter directly. The existing LocalRunStore owns opened-run
publication and references; three repetitive adapter helpers were deleted.
Each generate invocation has its own store, preserving overlapping-run isolation.

Retired the unused generic finalize hook, unused Episode snapshot overrides,
prepared Environment/task/Verifier tuples and old Runner ownership arguments.
Custom Environments override conversation(episode); per-conversation cleanup
uses that method's finally block. Task-file calls use output_dir= instead of
runner=. No new runtime owner, context, Plan, pipeline, class or storage mode.

Independent review reproduced and corrected three concrete defects: actual
Verifier subclass cleanup was bypassed; cancellation lost a seal-failure cause;
custom Environment validation still checked the old run hook. Closure now invokes
actual custom owners and closes shared non-idempotent Providers once, preserving
failures before/after ModelVerifier dependency cleanup. Cancellation keeps seal,
index and manifest disk causes. Invalid trace folders and IDs share one UUID.

Preserved review-before-effects, private histories, durable intent, partial
history, deadlines, redaction before persistence, attempted bounded cleanup,
cancellation propagation, sealed generation and append-only Verification.
Replaced obsolete finalization cases with actual conversation/context cleanup;
all migrated tests retain their safety assertions. Test-only recorded fixtures
use real Environment execution and actual store publication.

All offline gates pass: 354 tests (36.76s), strict mypy (48 files), Ruff, formatting,
lock check and wheel/sdist build. Built-wheel checks exercise direct retail data,
task-file validate/run, inspection, export and immutable reverification. Every
shipped Python file matches wheel bytes; retired modules remain absent and vLLM
SDK/UI imports stay isolated. No live inference or GPU execution was used.

Inclusive AST audit: 321 changed/new definitions across source, tests and examples,
all at most 20 lines. README fenced functions also meet the limit after normal
formatting. Unchanged long functions remain outside this slice; no claim of
whole-library compliance. Formatting and limits are both enforced, without
compressed signatures or removed assertions.

Honest size accounting: shipped Python 7,396 -> 7,413 lines (+17), 28 files,
95 -> 94 classes and 49 exports. Core 7,107 -> 7,124; integrations 165 and UI 124
unchanged. Runner deletes 431 lines, while retained behavior grows the existing
Environment, adapter and store. This simplifies ownership and the core API;
it does not substantially shrink total source. No dependency growth.

| File | Before | After |
| --- | ---: | ---: |
| runner.py | 454 | 23 |
| execution.py | 810 | 962 |
| store.py | 457 | 528 |
| task_package.py | 1,006 | 1,183 |
| cli.py | 252 | 290 |

The cumulative uncommitted checkout remains available for user review. Later
unrelated tickets 07–10 remain unstarted. Source/test baselines, audit and offline
evidence are retained under /private/tmp/agentinstruct-06b-* and the saved baseline
directories; no Git writes were performed.
