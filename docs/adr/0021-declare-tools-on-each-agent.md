---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0014
  - ADR-0015
  - ADR-0017
---

# Declare Tools on each Agent

## Decision

Each Agent definition declares its own tools alongside instruction, model and
optional reviewer. Omitted tools means an empty collection. Task has no tools
field, shared Tool pool or implicit assignment rule. Environment takes Task and
assembles each Agent's declared Tools directly from that Agent's definition.

Agent advertises and resolves calls only against its own assigned Tools. A Tool
declared on another Agent is unavailable unless explicitly declared on both.
Shared capability references retain explicit resource ownership; private results
and pending call state remain Agent/Episode-local. Validate Tool IDs within each
Agent's declaration without creating a global Tool-name registry.

Task continues to hold Agent definitions, input, segments, optional verifier,
limits and its automatically created Episode. Reviewer remains per Agent and
optional; verifier remains final Task judgment. Review-before-effects, durable
acceptance and Tool input/output validation remain unchanged.

## Consequences

This amends the earlier Task-level Tool declarations in ADR-0014/0015/0017.
Remove that field rather than adding aliases or a two-level permission system.
The optional file loader can retain existing authoring catalogs, resolving each
Agent's named assignments into its own tools definition; it emits no runtime
Task.tools field or global pool. The seven-module design gains no new owner.

Implementation remains unstarted. The [refactor plan](../../.scratch/library-design-audit/spec.md)
and glossary describe the target; production code and README are unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
