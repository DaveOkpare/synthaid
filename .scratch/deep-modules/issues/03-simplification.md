# 03: Simplify validation and conversion

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Delete duplicate traversals and conversion paths within their actual owners. Avoid extra wrappers and speculative modes.

## Verification

Test caller-visible behavior at the core/optional interfaces. Preserve live-network
isolation, SDK parity, durable effects, privacy and failure/cancellation evidence.
Use Ruff, strict types and the recursive function-size check.

## Answer

JSON freezing validates once and reuses its validator. Parsing preserves strict duplicate/nonfinite rejection without full re-encoding. Tools use the same JSON validation without redundant serialization; malformed arguments never reach the capability. No Provider/store/config wrappers were reintroduced. Incremental source/helper deletion and bounded operation measurements are recorded in the report.

See the [implementation report](../implementation.md) and [work map](../map.md).
