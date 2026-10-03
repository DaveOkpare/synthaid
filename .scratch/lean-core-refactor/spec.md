# Lean core refactor

Type: specification
Status: implementation
Date: 2026-10-03

The decisions below document the existing implementation checkpoint. The pending
[library design plan](../library-design-audit/spec.md) and
[ADR-0019](../../docs/adr/0019-task-owned-episodes-span-segments.md) now keep authored
phases as segments of one Task with a Task-owned Episode. They replace this
checkpoint's separate-record expansion and Environment-created Episode ownership.

## Objective

Generate domain data with actual Agents, an Environment, ordinary task records
and recorded Episodes. Keep maintenance cost low by deleting unused owners and
configuration hierarchies. [ADR-0011](../../docs/adr/0011-remove-plans-and-use-ordinary-task-records.md)
and [ADR-0012](../../docs/adr/0012-keep-runner-as-an-environment-task-loop.md) capture
the user's direction; ticket 06b implements the minimal Runner amendment.

## Decisions

- Agent owns instruction, model, Tools, Reviewer and its acceptance/revision loop.
- Environment owns actual Agents, conversation scheduling, execution lifecycle
  and optional final Verification of the completed Episode's chat history.
- Episode owns accepted messages/events and durable snapshots. It contains the
  whole conversation, including multiple user/assistant rounds until termination
  or the configured round limit.
- Runner only takes an Environment and prepared tasks/segments, loops them and
  calls the Environment. No preparation, lifecycle state, persistence or final
  Verification machinery. Environment invokes optional final Verification after
  the conversation ends, independently of per-Agent Review; export stays outside.
- Delete all Plans, ToolContext, StepProgress, AgentTool, runtime mapping/context
  facades, Runner factories and built-in control Tools. No renamed substitutes.
- Applications prepare data and create subsequent tasks in Python. Existing
  task files stay an optional adapter; phases expand into separate records.
- Responses and Chat Completions stay supported. vLLM uses the same HTTP client
  via base_url, with an optional external server launcher and no SDK import.
- Historical saved Trace JSON remains readable. Retired Python APIs and internal
  configuration catalogs deliberately change; preserve the actual evidence format.

## Required behavior

Review before effects; commit accepted intent before Tool execution; private Tool
and reasoning visibility; rejected-draft isolation; weighted scores/revision
budgets; local schema validation; strict JSON; credential redaction; partial/error
and cancellation evidence; bounded cleanup; immutable sealed generation;
append-only reverification; safe source paths and portable dataset exports.

Task-file validation/rendering must not instantiate live Agents/clients or run
inference. Readers keep JSON/JSONL/CSV/directory input safeguards and record
identity/origin/digest. No ETL DSL, plugin discovery or configuration container.

## Checkpoint

[05c](issues/05c-remove-plans-and-lean-task-loop.md) replaces unfinished05b and the
requested Runner work in06. Migrate tests and examples to actual-object APIs;
explicitly retire obsolete-contract cases. Run all current locked offline checks,
record measured deletions separately from moves, then stop for code review.

[06b](issues/06b-minimal-runner-and-environment-episodes.md) replaces the lifecycle
ownership retained in 06a with the accepted Environment/task loop. Retire unused
generic finalization and snapshot overrides; actual scoped cleanup remains.
Later unrelated tickets remain unstarted until the user's next review checkpoint.

[07](issues/07-consolidate-authoring-invariants.md#answer) completes the remaining
bounded authoring cleanup after Plan removal. Task files and rendered records
are unchanged; Environment cuts stay deferred, and later 08–10 remain unstarted.

[Work index](map.md) · [Plan](../../tasks/plan.md) · [Interface](interfaces.md)
