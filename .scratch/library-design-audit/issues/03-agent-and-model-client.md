# 03: Agent, SDK parity and Provider retirement

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Keep Agent settings stable and execution state invocation-local. Adopt the pinned SDK after parity and retire Provider/wire copies while retaining strict local acceptance and schema checks.

## Answer

Implemented under the user's authorization to execute [the specification](../spec.md).
Real offline SDK requests cover both APIs, safe errors/no retries, refusals/incomplete output, exact ordered reasoning continuation, typed nested schemas, separate clients/instructions and borrowed ownership in test_model_calls.py.

See [the implementation report](../implementation.md) for source accounting,
release evidence, migrations and limits. Later corrections from final review are
included in this completed slice; no live inference was required.
