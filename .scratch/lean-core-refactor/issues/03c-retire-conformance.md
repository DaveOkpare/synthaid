# 03c: Remove conformance execution and document the simpler boundary

Type: implementation
Status: resolved
Blocked by: 02

## Description

Delete canonical and old-path conformance modules, certification-only sample profile/documentation, and retired command tests. Preserve ordinary transport/tool/schema tests and update import-safety checks. Record the deliberate ADR amendment and short CLI usage.

## Scope

Five logical units: conformance module pair removal; obsolete conformance directory removal; import-safety tests; README; ADR amendment and tracker documentation. Root owns integration and full quality gates.

## Verification

Import/collection safety, legacy saved fixtures, full deterministic suite, lint/typing, lock/build/package checks, and actual recursive source counts.

## Answer

Resolved 2026-10-02. Deleted both conformance module paths and the obsolete pinned certification profile/docs. Removed command/schema identity checks for the retired command while preserving import, no-effect, collection, ordinary generation, and historical saved-Trace coverage. README now explains minimal endpoint configuration, the packaged launcher, and the deliberate command retirement. ADR-0008 explicitly amends ADRs 0005–0007.

Root reviewed these changes; independent read-only review found no actionable issues. Import/saved-fixture checks pass 10 tests; the complete suite passes 586. Lock check, Ruff, formatting, strict typing, whitespace check, wheel/sdist build, and archive checks pass. Built-wheel imports retain all 78 top-level exports and the short CLI without an SDK/engine import. Every Python file in the final wheel matches source. Retired modules and vLLM dependency are absent; scratch/plan/run files are excluded.

No live server, model download, or GPU inference was run. Tests use fake processes and HTTP transports. Final source accounting is in the parent answer.
