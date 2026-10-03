# 07: Consolidate authoring invariants

Type: implementation
Status: resolved
Blocked by: 03
Date: 2026-10-03

## Description

Reduce repeated defaults, validation and field conversion in the optional
TaskPackage adapter. The original ticket predates ADR-0011 and referred to Plan
classes and task_config.py, which are now deleted. Do not restore those owners.
Keep unresolved task-file metadata and rendered ordinary records compatible.

The user authorized this next slice and explicitly deferred Environment cuts.
Leave Environment, Agent execution, Runner and the recording workflow unchanged.

## Acceptance criteria

- [x] Finish remaining concrete authoring duplication after 05c deleted the
      duplicate Plan/configuration layer; retain actual scalar/default checks.
- [x] Preserve constructors, task-file syntax, strictness, error stages, rendered
      fields and historical snapshots; add no compatibility wrappers.
- [x] Load/compile/validate do not construct Agents, Providers or HTTP clients;
      rendered records remain detached immutable JSON.
- [x] Keep custom references, Tool assignments, phase rubrics, Provider defaults
      and accepted runtime metadata readable.
- [x] All changed/new definitions are at most 20 inclusive physical lines with
      normal formatting. No new configuration model, catalog, context, pipeline
      or validator framework; short forwarding helpers do not count as a cut.

## Verification

Save the current source/tests and compiled example records before editing.
Compare rendered payloads and existing malformed-input behavior with that
baseline. Run task-adapter, package-safety, seed-source, structured-output,
import-safety and CLI tests; then all 354 current tests, strict types, lint,
format, lock/build and built-wheel usage checks. Add only meaningful uncovered
regressions. Record actual source changes and stop for user code review.

## Likely files and scope

TaskPackage authoring/default conversion, and existing leaf validation only
where the audit demonstrates duplication. Seed-reader/compilation-loop redesign
belongs to ticket 09; model-call evidence belongs to 08. Both remain later work.

Baseline: 354 tests; 7,413 shipped Python lines, 28 files, 94 classes, 49 exports;
task_package.py 1,183 lines. Retain cumulative uncommitted work; no Git writes.

## Answer

The original Plan/configuration duplication was already removed in 05c under
ADR-0011. This bounded follow-up removes the remaining duplicated directory
diagnostic assembly and its unused optional-members argument. Missing and
undeclared names now share one ordered formatter, preserving group order,
sorted package-relative paths, exception text and causes.

Only _directory_members changed in production: 29 -> 17 inclusive lines;
task_package.py 1,183 -> 1,171 lines. No new helper, class, dependency, catalog,
configuration model or compatibility wrapper. Environment, Runner and runtime
execution remain byte-identical to the previous checkpoint.

Numeric/Boolean guards remain shared through existing conversion functions;
Criterion/Rubric already own their domain invariants. Direct Agent defaults
and task-file defaults intentionally differ. A new general default resolver
would obscure those contracts and change snapshots; none was introduced.

Independent checks compare all 24 compiled records from 15 examples and 40
malformed authoring inputs with the saved baseline: exact payloads and exact
exception type/message match. A separate 66-state directory probe preserves
outcomes, diagnostic text and cause types. Existing tests were not modified to
pass; one 15-line regression checks simultaneous missing instruction and
multiple undeclared files, created in reverse order. It also passes against
the saved original implementation.

All gates pass: 355 tests (37.48s), strict mypy (48 files), Ruff, formatting,
lock check and wheel/sdist build. Built-wheel proof checks all shipped source
bytes, adapter validate/run/inspect/export, immutable reverification and the
actual retail example; retired imports remain absent. No live inference.
The changed production function and new test are both within the 20-line limit.

Actual size: shipped Python 7,413 -> 7,401 lines (-12), core 7,124 -> 7,112;
integrations 165 and UI 124 unchanged. Still 28 files, 94 classes and 49 exports.
Source/test/example baselines and replay evidence are retained at
/private/tmp/agentinstruct-before-07; final gates at /private/tmp/agentinstruct-07-*.

The audit also found repeated phase-file reads in TaskPackage.load. Decomposing
that long loader to capture the validated text once belongs with the later
preparation slice; it was recorded on 09. This slice does not split the loader
into many forwarding helpers or change the compilation loop. Later 08–10 remain
unstarted, and Environment simplification is deferred at the user's request.
Stopped for code review; cumulative uncommitted work preserved, no Git writes.
