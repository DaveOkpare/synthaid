# 01: Record the compatibility baseline

Type: implementation
Status: resolved
Blocked by: none

## Description

Establish the compatibility contract before moving implementation. Record existing exports/signatures, representative Task syntax, and persisted Trace formats. Amend architectural ownership explicitly: the Agent runtime owns message Review and the Runner invokes final Verification.

## Acceptance criteria

- [x] Record top-level/documented import paths, extension hooks, factory overrides, task defaults, CLI behavior, and recorded-artifact contracts; reuse the existing tests that already exercise them.
- [x] Add only missing behavior regressions using small deterministic custom Agents and saved Trace fixtures, including a representative old Trace independent of the original Task package.
- [x] Add an ownership ADR referencing ADRs 0002–0006 and the refactor spec; preserve Review-before-effects, private Tools, immutable Plans, and durable Trace semantics.

## Verification

Run `uv run --locked pytest tests/test_release_workflow.py tests/test_components.py tests/test_cli.py tests/test_import_safety.py`; run `uv run --locked mypy` for new fixture types. Establish the full deterministic baseline and record any pre-existing failure. Check plan/spec links.

## Likely files and scope

Medium: `tests/test_release_workflow.py`, one compatibility-test module, small fixture artifact directory, `docs/adr/0007-agent-owned-review-and-lean-core.md`. Keep fixtures data-only.

## Answer

Completed 2026-10-01 through separate test and documentation subagents, with an independent read-only review and root verification. Existing production source and public interfaces are unchanged.

- [Compatibility inventory](../baseline.md) records all 78 exports, extension hooks/factories, Task defaults, CLI behavior, and saved formats against existing coverage.
- [Two new tests](../../../tests/test_refactor_compatibility.py) cover a fixed historical Trace, private participant projection, final Verification sidecar overlay, exact target export, and immutable source bytes without original component imports or network access.
- [Fixture provenance](../../../tests/fixtures/compatibility/README.md) documents the unaltered 18,428-byte capture from the pre-refactor commit and synthetic custom Task.
- [ADR-0007](../../../docs/adr/0007-agent-owned-review-and-lean-core.md) establishes Agent-owned message Review and independent Runner-owned final Verification; runtime consolidation remains pending.

Pre-change suite: 552 passed in 48.38s. Post-change full suite: 554 passed in 48.89s. Focused compatibility/release/components/CLI/import tests: 55 passed. Lock consistency, whole-repo Ruff lint/format, strict mypy (53 files), source/wheel build and package contents passed. Independent review reported no actionable findings.

Task 02 has not started. The user requested code review and explicit approval before proceeding to Task 02.
