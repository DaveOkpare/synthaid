# 02: Generation and evaluation protocols

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Use small structural interfaces for actual interchangeable domain behavior, preserving Agent approval/effects and Episode recording.

## Verification

Test caller-visible behavior at the core/optional interfaces. Preserve live-network
isolation, SDK parity, durable effects, privacy and failure/cancellation evidence.
Use Ruff, strict types and the recursive function-size check.

## Answer

Generator and Evaluator support plain domain adapters without inheritance or SDK attributes. Agent preserves approval/effects ownership; malformed results cannot authorize Tools. Recorded evaluator failures remain distinct from verification publication failures, including OSError from a domain evaluator. Retail/scripted adapters and reusable arithmetic/custom execution cases exercise these seams.

See the [implementation report](../implementation.md) and [work map](../map.md).
