# 06: Simplify Runner assembly and lifecycle

Type: implementation
Status: resolved
Blocked by: 03, 05b

## Description

Consolidate repeated construction/preflight into small internal assembly functions and reuse quality construction for final Verification/reverification. The Runner delegates Agent setup and retains seed iteration, deadlines, cleanup, durable publication, and final Verification.

## Acceptance criteria

- [ ] Current factory keywords and explicit task references converge on one construction implementation; preserve fresh instances, component validation, and preflight before participant inference.
- [ ] Runner delegates per-Agent Review configuration to the Agent runtime; final Verification uses the same construction/evaluation path as reverification without reusing closed Providers.
- [ ] Cancellation, per-stage error categories, finalization, cleanup deadlines, partial persistence, and index-after-snapshot ordering pass existing tests with reduced duplicated setup.

## Verification

Run `uv run --locked pytest tests/test_runner.py tests/test_verification.py tests/test_model_quality.py tests/test_hardening.py tests/test_release_workflow.py`; run full deterministic tests at this ownership checkpoint. Record actual construction/lifecycle lines removed.

## Likely files and scope

Medium: `runner.py`, `components.py`, `verification.py`, `quality_provider.py`, `tests/test_runner.py`. Small private assembly helpers may live in the existing lookup module. Keep optional finalizer and factory compatibility; do not add a dependency container.

## Answer

Superseded and implemented by the user's direct Runner(Environment, records)
direction in [05c](05c-remove-plans-and-lean-task-loop.md#answer). Earlier factory
preservation criteria are retired under ADR-0011. Runner now owns record iteration,
lifecycle/cleanup/seal/publication and independent final Verification; actual
binding is optional task-file adapter work. 27 direct Runner regressions and the
full332-test checkpoint pass. No separate later implementation was started.
