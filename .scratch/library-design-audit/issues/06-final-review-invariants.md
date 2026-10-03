# 06: Preserve strict JSON and callable judgment evidence

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Continue the completed refactor with a focused correctness review. Frozen Task
input/provenance currently accepts nonfinite floats and fails later during
recording. A callable Judge returning Judgment currently loses that value's
evidence while normalizing its verdict and score.

## Acceptance criteria

- Task construction rejects nested nonfinite JSON input/provenance without I/O.
- Callable Judgment evidence survives validation and reaches review/final records.
- Verdicts and weighted scores are still validated/recomputed locally.
- No new runtime owners or helpers; every shipped function stays under 20 lines.

## Verification

Add regression tests at Task and Judge/Episode boundaries, then run the canonical
full suite, Ruff, strict mypy and build/wheel checks. Update the final source
inventory and [implementation report](../implementation.md).

## Answer

Corrected strict JSON validation in Episode's canonical json_data boundary, so
Task input/provenance fail locally before recording. Callable Judge evaluation
preserves immutable evidence from returned Judgment values while still validating
verdicts and recomputing scores. Tests cover three nonfinite numbers nested under
both input and provenance, and evidence persistence in review/final verification
with and without a Rubric. 204 offline tests, Ruff, strict mypy, wheel/sdist builds
and isolated built-wheel execution pass. All source functions remain under 20
lines. Five lines added; no new helper, class, dependency or export.

See [the report](../implementation.md) and [current metrics](../metrics.json).
