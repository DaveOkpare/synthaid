---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0018
  - ADR-0019
---

# Create an identified Episode with each Task

## Decision

Constructing a Task automatically creates its own empty Episode. Episode creates
its unique UUID-based ID during construction. task.episode, task.episode.id and
the initially empty accepted messages view are immediately available. Use a
per-instance default factory, never a shared Episode default. A caller does not
supply an Episode or ID to construct an ordinary Task.

Task construction performs no file writes, model/Tool calls or live resource
acquisition. Episode creation and persistent recording are separate operations.
Runner owns output_dir and opens the existing Episode at output_dir / episode.id
before execution. Episode.open(path) establishes durable recording without
changing identity; acceptance must still be durable before Tool effects.

The first execution uses the exact Episode object and ID created with Task.
Runner and Environment do not replace them. All Task segments use that Episode;
final verification still consumes its sealed accepted history. Loading historical
Episode data retains its recorded ID rather than generating a replacement.

## Consequences

This replaces ADR-0019's None-before-execution Episode and Runner-side creation.
No output directory moves into Task or Environment, and no recorder owner or
configuration hierarchy is added. Persist ordinary Task declarations/provenance,
not a recursive reference to the live Task.episode.

The [plan](../../.scratch/library-design-audit/spec.md) recommends a Task-bound
Environment constructor with async run and a fresh Task for each independent
execution. Those lifecycle/reuse refinements remain proposals; this decision
accepts automatic Episode creation and use of its initial identity for execution.

Implementation remains unstarted. Production code and README are unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
