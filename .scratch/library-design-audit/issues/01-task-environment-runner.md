# 01: Task, Environment and Runner

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Task creates its own Episode/UUID; Runner opens it and constructs one Environment per Task; constructor-bound Environment executes ordered segments and returns None.

## Answer

Implemented under the user's authorization to execute [the specification](../spec.md).
Identity, supported roles, immutable definitions, direct/structural execution, concurrent reuse, segment activation, final verification and primary failures are covered by test_generation.py and test_recording.py.

See [the implementation report](../implementation.md) for source accounting,
release evidence, migrations and limits. Later corrections from final review are
included in this completed slice; no live inference was required.
