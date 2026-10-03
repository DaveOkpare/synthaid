---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0016
  - ADR-0017
---

# Construct Agent definitions and revise from review

[ADR-0023](0023-use-agent-directly-and-keep-execution-state-local.md) supersedes
the separate AgentDefinition constructor and agent_class selection below. Use
Agent directly, with execution state kept in Episode/local calls. The feedback
and revision decision remains in force.

## Decision

Provide AgentDefinition(...) as a small directly importable settings record in
agent.py. Task.agents maps participant names to definitions. It declares model,
instruction, own Tools, optional reviewer and revision limits; custom generation
selects a concrete Agent class with agent_class=Agent as the default. It is inert,
has no Episode or conversation/revision state, and snapshots supplied collections.
Environment creates fresh runtime Agents from definitions for each Task execution.
Definitions and explicitly owned Tool/Judge dependencies can be reused.

This replaces the plan's raw Agent-setting mappings with an explicit constructor.
It does not add an eighth domain module, registry, factory or parallel AgentConfig
hierarchy. Supporting records stay with their existing owner. The public name
AgentDefinition and agent_class argument are the plan's proposed spellings.

Reviewer is the same reusable Judge used for final verification. Its validated
result includes verdict/criteria and text feedback describing needed corrections.
Agent.turn supplies its rejected draft and that guidance to generate(history)
using temporary private history. Agent authors the replacement and submits it to
review again, within its configured max_revisions. Judge evaluates; Agent owns
drafts, the revision budget, acceptance and approved Tool execution.

Drafts, feedback and revision links are recorded as Episode Events, without
adding the temporary revision history to accepted messages, peer observations or
default training exports. Rejected Tool proposals produce no effects. Preserve
existing review-error/exhaustion policy and its restriction against accepting
rejected Tool calls/completion signals. Final Task.verifier consumes sealed
accepted history without rewriting it or initiating further Agent revisions.

## Consequences

Direct callers have a constructor rather than remembering nested Agent dictionary
keys. Optional authoring loaders emit the same values. Reusing settings does not
share runtime draft/Tool/conversation state, and custom generation receives the
same revision inputs as built-in generation without an extra ReviewRequest seam.
Explicit clients and shared capabilities retain their declared resource ownership.

Implementation is unstarted. The [refactor plan](../../.scratch/library-design-audit/spec.md)
and glossary describe the target; production code and README are unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
