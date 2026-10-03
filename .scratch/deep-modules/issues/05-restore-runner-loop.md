# 05: Restore Runner to the specification's Task loop

Type: implementation
Status: resolved
Date: 2026-10-03
Baseline: 5367d23

## Description

The user rejected the Runner-owned lifecycle introduced during simplification.
Restore the original specification: Runner opens each Task's existing Episode,
invokes its Environment and collects results. Environment owns execution and
finalization. Keep the working protocol seams and application-owned resources;
introduce no lifecycle wrapper, registry or new owner.

## Verification

Prove ordered invocation/identity/client forwarding, explicit open failure and
unmodified propagation of custom Environment errors. Runner must not begin,
apply a deadline, seal or verify on behalf of a custom Environment. Standalone
UserSimEnv must preserve the recorded deadline, failure, cancellation, durable
Tool approval and final-verification behavior. Run the full offline release gate.

## Answer

Restored Runner to 31 lines with only initialization and the Task loop. It opens each Episode, invokes Environment and collects it. Required execution safeguards now belong to UserSimEnv; custom errors propagate unchanged. All 225 offline tests, Ruff, strict mypy, packaging, seven examples and the CLI/TUI workflow pass. See the [correction report](../runner-correction.md) and [work map](../map.md).
