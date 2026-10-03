# 09: Simplify seed preparation

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Rebased onto ordinary Python records and the optional adapters/task_files.py. Compilation is inert; load_tasks constructs configured Agents/Tools/Judges and one Task per input, with authored phases preserved as segments.

## Verification

Use the canonical behavioral suites: tests/test_generation.py,
tests/test_model_calls.py, tests/test_recording.py, tests/test_task_files.py,
tests/test_cli_inspection.py, tests/test_import_safety.py and
tests/test_vllm_startup.py. The [release report](../../library-design-audit/implementation.md)
contains the complete reproducible gate and measured baseline comparison.

## Answer

The user authorized execution of the [seven-module plan](../../library-design-audit/spec.md).
JSON/JSONL/CSV/directory/Python inputs, IDs and origins, source-versus-record failures, strict rendering, symlink/layout safeguards and inert custom-reference validation pass in tests/test_task_files.py and tests/test_import_safety.py. examples/seed-sources/run.py demonstrates ordinary generator preparation. Base/phase files are captured once so provenance digests use the exact validated text. Seed/bind/TaskPackage owners and their old test commands are removed.

Resolved through that plan's completed slices; no additional compatibility layers
or live service certification were introduced.
