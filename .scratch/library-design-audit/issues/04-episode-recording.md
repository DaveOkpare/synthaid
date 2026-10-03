# 04: Single Episode representation

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Consolidate accepted history, durable recording, safe JSON/export, immutable generation and append-only verification into the Task-owned Episode.

## Answer

Implemented under the user's authorization to execute [the specification](../spec.md).
Actual fsync failures stop effects; opening/sealing failures retain evidence; cancellation preserves primary errors; output confinement, historical reads and immutable reverification pass in test_recording.py and test_cli_inspection.py.

See [the implementation report](../implementation.md) for source accounting,
release evidence, migrations and limits. Later corrections from final review are
included in this completed slice; no live inference was required.
