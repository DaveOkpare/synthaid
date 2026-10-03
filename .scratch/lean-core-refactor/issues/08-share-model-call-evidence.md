# 08: Share model-call evidence

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Rebased onto the seven-module specification. Agent owns the shared SDK request/evidence path; model Judge uses that path and applies exact judgment semantics. There is no Provider/quality transport wrapper family.

## Verification

Use the canonical behavioral suites: tests/test_generation.py,
tests/test_model_calls.py, tests/test_recording.py, tests/test_task_files.py,
tests/test_cli_inspection.py, tests/test_import_safety.py and
tests/test_vllm_startup.py. The [release report](../../library-design-audit/implementation.md)
contains the complete reproducible gate and measured baseline comparison.

## Answer

The user authorized execution of the [seven-module plan](../../library-design-audit/spec.md).
Both APIs, usage/request identity/latency, malformed/refusal/incomplete output, strict local schemas, safe errors, redaction and no retries pass at actual Agent/Judge interfaces in tests/test_model_calls.py. Borrowed client ownership and concurrent invocation isolation pass. The old providers/responses/model-quality commands were retired with those modules.

Resolved through that plan's completed slices; no additional compatibility layers
or live service certification were introduced.
