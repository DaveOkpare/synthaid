---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0011
  - ADR-0014
  - ADR-0015
  - ADR-0016
  - ADR-0017
  - ADR-0018
---

# Task-owned Episodes span segments

[ADR-0020](0020-create-an-identified-episode-with-each-task.md) moves Episode/ID
creation to Task construction. The None-before-execution field and Runner-created
Episode below are historical; Task ownership and segment continuity remain.

## Decision

One Task execution owns one Episode across its ordered segments. Task.segments
contains ordinary named records with Agent-specific instruction additions;
Task.episode starts as None and holds the current/latest execution's history and
output. It is not a configuration argument or implicit continuation input.

Runner retains output_dir, creates an Episode at a unique path for each Task
execution and attaches it before Environment.setup(task). Environment borrows
that Episode. run() executes the Task's segments, seals generation once, invokes
Task.verifier on sealed accepted history and returns None. Runner.run collects
Task.episode after each execution. Standalone callers attach an Episode before
using the same setup/run interface.

```python
for task in taskset:
    task.episode = Episode(output_dir / uuid4().hex)
    await environment.setup(task)
    await environment.run()
    episodes.append(task.episode)
```

Set up participants once per Task execution. Only the active segment's instruction
additions are available, alongside base instructions. Activate the next segment
after ordinary conversation completion and resolved approved Tool exchanges.
Retain accepted shared messages and each Agent's private Tool history; record
segment activation and provenance without rewriting earlier history. Failure,
cancellation or task-wide truncation stops later segments and preserves partial
evidence; failed/invalid generation cannot be promoted by final judgment.

Repeating a Task attaches a fresh Episode without clearing or mutating the earlier
one. Conversations/review state do not cross Task executions implicitly.
Concurrent executions use distinct Task and Environment instances, since one
Task.episode reference cannot represent concurrent executions. Shared injected
infrastructure retains explicit ownership.

## Consequences

The optional loader retains authored phases as segments within one Task rather
than expanding them into independent Tasks. Generation seals once at Task end;
Task.verifier remains final judgment across the executed segments. Agent.reviewer
remains optional and per participant. Durable intent before Tool effects, privacy,
failure evidence and append-only reverification remain.

This replaces Environment-created/output Episode ownership in ADR-0017 and the
per-execution path argument in ADR-0018, retaining output_dir on Runner. It also
amends ADR-0011's separate-record expansion. No Plan, TaskContext, StepProgress,
advancement Tools, Segment class/module or recording manager is reintroduced.
Only serializable Task declarations/provenance belong in persisted Task metadata;
do not serialize the live Task.episode reference into itself.

[Harbor multi-step tasks](https://docs.harborframework.com/core-concepts/tasks/multi-step)
inspire ordered instructions and continuation; shared history by default and
Task-owned Episode are choices for this library, not claims about Harbor's interface.

Implementation remains unstarted. The [refactor plan](../../.scratch/library-design-audit/spec.md)
and glossary describe this target; production code and README remain unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
