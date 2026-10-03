---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0016
  - ADR-0017
  - ADR-0022
---

# Use Agent directly and keep execution state local

[ADR-0024](0024-use-required-assistant-and-optional-user-task-roles.md) narrows
Task's participant assignments below to a required assistant target and optional
user within the same Task.agents mapping. Direct Agent use and local execution state
remain unchanged.

## Decision

Use Agent(model, instruction, tools=(), reviewer=None) directly. Task.agents maps
participant names to configured Agent instances. Environment validates and uses
those objects. Custom generation constructs an Agent subclass and supplies it
in the same mapping. Remove the separate AgentDefinition constructor, agent_class
setting and definition-to-runtime construction.

Agent combines stable settings with generation/turn behavior. Episode owns each
Task's accepted/private history, continuation state and recorded evidence. Drafts,
review feedback and revision counters are local invocation variables. Agent does
not store a current Episode, pending calls or mutable per-run history. This keeps
independent execution possible with the same built-in Agent, without cloning or
reset methods. Stateful custom dependencies need separate caller-owned instances.

Environment passes participant identity, active instruction projection and its
borrowed client as invocation inputs rather than mutating Agent. Model-backed
turn/generate accept an optional client keyword; explicitly configured Agent
clients take precedence. Borrowed clients and Tool/Judge capabilities retain their
declared ownership. The review/revision flow from ADR-0022 remains unchanged.

## Consequences

Callers learn one Agent constructor and can use that object directly. This
supersedes ADR-0022's additional settings record and ADR-0017's fresh runtime Agent
construction rule. Isolation is a property of Episode and invocation state,
instead of a second representation of every Agent. The seven-module design and
Task-owned Episode across segments remain unchanged.

Implementation is unstarted. The [refactor plan](../../.scratch/library-design-audit/spec.md)
describes the target; production code and README are unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
