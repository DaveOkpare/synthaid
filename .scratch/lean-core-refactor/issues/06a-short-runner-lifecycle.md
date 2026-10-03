# 06a: Short Runner lifecycle methods

Type: implementation
Status: resolved
Blocked by: 05c
Date: 2026-10-02

## User direction

Proceed to the next slice; _run_tasks is still bloated. Every function/method in
this Runner slice must be at most 20 physical lines, including its signature,
blank lines and comments. Prefer deleting duplicated branching over moving a
large function to another file. Keep readable formatting and no semicolon tricks.

This direct Runner correction takes priority over the old 07 authoring ticket.
Apply the same length rule to subsequent touched code. No new public classes,
Plan/context/container types, dependencies or factories. Keep current API and
all 332 behavior tests without weakening assertions.

## Dependent slices

1. Extract repeated event/error handling and real resource-close operation into
   short private methods on existing Runner; preserve old entry point behavior.
2. Separate Episode execution/finalization/sealing/verification/publication from
   the task loop. Existing Runner owns private run state, not a new state wrapper.
3. Make _run_tasks a short readable coordinator; preserve early-storage errors,
   partial preparation cleanup, cancellation, deadlines, index/seal ordering,
   borrowed vs owned Verifier lifetime and final immutable evidence.
4. Full locked offline gates; independent review; automated inclusive function
   length audit; publish actual total line/method changes, then stop for review.

## Verification

Current test_lean_runner (27 cases), verification, seeds, inspection, CLI and
historical-artifact behavior checks; full 332-test suite. Add tests only for a
real uncovered regression or an explicit new constraint. Strict mypy, Ruff,
format, lock/build, wheel/direct-example smoke. Compare against saved previous
Runner in /private/tmp; do not restore/reset cumulative worktree changes.

## Answer

Completed the Runner-only slice. The public Python API and task-file adapter
remain unchanged. `_run_tasks` coordinates initialization, execution, cleanup
and run completion; the task loop calls Episode execution, cleanup, sealing,
final Verification and publication in order. All 32 functions in runner.py are
at most 20 inclusive physical lines; `_run_tasks` is 19 lines instead of 347.

The existing Runner holds private lifecycle fields. A shallow copy per invocation
gives overlapping task-file runs separate mutable state, without introducing a
new class or context/container abstraction. The copy shares the stateless store
configuration. Four once-used helpers were folded into their owning operation
while retaining the length limit. Final counts are derived from published
references instead of maintaining a second mutable counter.

Preserved setup/run deadlines, custom TimeoutError classification, partial
preparation cleanup, shielded cleanup, cancellation propagation, attempted-once
owned resource close, borrowed Verifier lifetime, failure diagnostic redaction,
both persistence clamps, seal-before-Verification ordering and immutable evidence.
The independent review caught a combined cancellation/index-failure regression;
the final version preserves the disk diagnostic and still propagates cancellation.

Two behavioral regressions were added: interleaved task-file runs through one
Runner, and cancellation followed by index failure. All 29 Runner tests pass
against both the saved baseline and final implementation. The pre-existing
332-test suite remains intact; the full suite now passes 334 tests. New test
functions also meet the 20-line limit. No rule-only test framework was added.

Locked offline gates passed: full pytest (334, 36.47s), Ruff, formatting, strict
mypy (47 files), lock check, wheel and sdist build. The built-wheel proof exercised
task-file validation/generation, inspection, export, immutable reverification and
the direct retail-domain example. Every shipped Python file matches the wheel;
retired modules are absent and vLLM/UI imports remain isolated.

Size accounting: runner.py 455 -> 454 lines, definitions 9 -> 32; whole shipped
Python source 7,397 -> 7,396 lines, 28 files, 95 classes and 49 exports. Core has
7,107 lines; integrations 165; UI 124. No new dependencies, classes or public
exports. This improves local readability; it is not a substantial size reduction.
The extra private methods cost navigation, as the independent review noted.

Only this Runner slice has been brought under the limit. Apply it to subsequent
touched functions; do not claim the rest of the library already complies. Later
authoring/model/seed work remains unstarted. Stopped for the user's code review.
