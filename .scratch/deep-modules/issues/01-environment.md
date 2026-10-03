# 01: Narrow Environment and structural execution

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Remove generic resource management and verifier assembly. Keep Task execution, outcomes and final verification. Applications own resource lifetime.

## Verification

Test caller-visible behavior at the core/optional interfaces. Preserve live-network
isolation, SDK parity, durable effects, privacy and failure/cancellation evidence.
Use Ruff, strict types and the recursive function-size check.

## Answer

Environment is a one-method protocol; stateless UserSimEnv retains only segment/conversation execution (196 to 45 lines). Runner owns the common recording/deadline/finalization lifecycle. Task takes prepared evaluators; applications own external resources. Domain execution, failure, deadlines and cancellation are verified.

See the [implementation report](../implementation.md) and [work map](../map.md).
