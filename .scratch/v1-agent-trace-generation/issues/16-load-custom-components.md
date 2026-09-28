# 16: Load custom components through explicit references

**What to build:** Let extension authors run a complete Task using built-in short identifiers or explicit Python references for custom Agents, Environments, Tools, Reviewers, and Verifiers without bypassing framework invariants.

**Blocked by:** 05 — Verify and reverify sealed Traces; 08 — Support robust multi-Tool interactions; 09 — Retain history across Task Steps

**Status:** resolved

**Type:** implementation

- [x] Built-in components resolve through a small explicit registry and custom components resolve through explicit import references.
- [x] Resolution is lazy, validates the required public protocol immediately, and reports the exact failing reference.
- [x] An explicit lookup failure never silently falls back to a similarly named built-in.
- [x] A custom Environment receives only the narrow immutable Task Context and run-bound Agent facades.
- [x] A custom Environment can orchestrate a multi-party interaction in ordinary asynchronous Python without direct recorder or Provider access.
- [x] Custom Tools, Reviewers, and Verifiers retain the same review, privacy, persistence, and scoring guarantees as built-ins.
- [x] One fixture Task demonstrates a custom Environment and at least one other custom component through validation, execution, Verification, and persisted Trace output.

## Answer

Implemented an explicit immutable built-in registry and `module:Class` references
for Agents, Environments, Tools, Reviewers and Verifiers. Package loading resolves
only configured definitions and validates async methods and constructor signatures
without creating runtime components or model clients. Lookup, construction and
protocol failures identify the exact selected reference; explicit failures never
fall back. Runner and reverification construct fresh instances and validate their
runtime protocol before use. Existing injected factories and placeholders remain
supported.

Custom Environments use a no-argument constructor, narrow immutable Task Context
and existing trace-bound Agent facades. Multi-party ordinary async control flow
retains the existing reviewed, durable Message boundary, private Tool history and
framework scoring. Explicit function Tool references and subordinate Agent Tool
factory/configuration declarations use the same adapters. Agent Tool provenance
records the actual subordinate factory source, instruction and immutable declared
configuration; Function Tools retain their function identity.

Compiled Plans retain component source digests. Explicit implementation files
inside a Task Package are included in its source snapshot, while installed external
components retain their reference and available source digest. The
[offline custom-component example](../../../examples/custom-components/task.toml)
uses all five reference kinds, three participants and two Seeds through validation,
execution, review, Verification, persisted Trace output and reverification. See
[authoring and constructor contracts](../../../README.md#load-custom-components).

Initial validation: 17 new tests at the public Runner/Task Package/CLI artifact seams;
268 affected component, import-safety, CLI, Runner, review, Tool, Verification,
dialogue, Step, collection and package-safety tests pass. Strict mypy, Ruff lint,
Ruff formatting and `git diff --check` pass. No live inference, full-suite or build
run was performed; the final release workflow remains ticket 19.

Review follow-up: definition validation now distinguishes ordinary methods from
static and class methods without constructing components. Two public reference
regressions cover a classmethod Agent, staticmethod Tool and both forms of optional
Environment finalizer through package validation, Runner and persisted Traces.
All 70 focused component, import-safety, Runner and Tool tests pass, as do strict
mypy, Ruff lint/format checks and `git diff --check`.
