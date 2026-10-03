# 02: Reusable Judge and callable Tool

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Use one Judge constructor/evaluate path for callable or model evaluation; Agent owns revisions, Episode owns verification, and each Agent explicitly owns its callable Tools.

## Answer

Implemented under the user's authorization to execute [the specification](../spec.md).
Exact weighted criteria, malformed verdicts, shared/concurrent Judges, independent revision budgets, Tool input/output validation, no rejected effects and explicit shared Tool privacy pass in test_generation.py and test_model_calls.py.

See [the implementation report](../implementation.md) for source accounting,
release evidence, migrations and limits. Later corrections from final review are
included in this completed slice; no live inference was required.
