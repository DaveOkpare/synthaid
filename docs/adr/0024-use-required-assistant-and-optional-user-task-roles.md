---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0023
---

# Use required assistant and optional user Task roles

## Decision

Task.agents keeps its mapping of Agent definitions, with only assistant and user
as supported keys. assistant is required and always the target Agent; user is
optional and may be omitted. Values are directly constructed Agent instances.
The default role is assistant, not an automatically invented Agent/model. Reject
a missing/None assistant, user-only Tasks and unknown keys. Do not introduce
separate Task.assistant or Task.user fields.

Role assignment belongs to the Task.agents mapping keys. Remove arbitrary
participant names and separate target selection; Agent keeps its existing direct constructor. Both
roles may have their own Tools/reviewer and use custom generation subclasses.
Domain personas remain instructions. No role subclasses or role registry are
needed. Environment runs the assistant alone or an assistant/user dialogue;
only the assistant may signal completion and is selected as the training target.

Segments retain these same participants and accept instruction additions only
for configured roles. Reviewers/verifiers and Tool/wire message roles are not
additional Agent types. Role and active instructions remain invocation-local;
sharing Agent settings does not share Episode/private history.

## Consequences

This restricts ADR-0023's Task.agents keys while retaining its mapping and direct Agent use.
The optional loader translates [agents.assistant] and optional [agents.user] into
that same mapping. Legacy target flags must agree with the fixed roles. Unsupported
participant names, user targets and instructions for an absent user produce
explicit migration/validation errors. Historical Trace identities remain readable.

Implementation is unstarted. The [refactor plan](../../.scratch/library-design-audit/spec.md)
describes the target; production code and README are unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
