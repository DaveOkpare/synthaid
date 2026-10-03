---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0012
  - ADR-0015
  - ADR-0017
---

# Runner owns the output directory

[ADR-0019](0019-task-owned-episodes-span-segments.md) retains Runner-owned output_dir
and path allocation, but attaches Episode to Task before setup. The episode_path
setup keyword and Environment-created Episode below are superseded.

## Decision

Runner takes output_dir alongside Environment and Tasks. Environment's constructor
accepts execution dependencies, without an output_dir setting. Runner normalizes
the root to a Path and chooses a unique Episode destination for every execution,
including repeated Tasks and repeated Runner.run calls.

Runner passes that destination to setup(task, *, episode_path), then calls run().
A standalone Environment caller supplies its execution path through the same
setup argument. Environment prepares the Task's participants and independent
Episode; Episode owns durable recording at the supplied path. Tool-call intent
must still be recorded before effects, rather than saving only after run returns.

```python
environment = Environment(client=model_client)
episodes = await Runner(environment, tasks, output_dir="runs").run()
messages = episodes[0].messages
```

## Consequences

Output placement belongs to the batch caller. Conversation execution and final
verification remain in Environment; accepted history and persistence remain in
Episode. No output configuration on Task or recording-manager class is introduced.
This amends ADR-0012's adapter-owned output directory and the earlier plan's
Environment constructor example, while retaining the setup/run lifecycle.

Implementation is pending. The [refactor plan](../../.scratch/library-design-audit/spec.md)
and glossary describe the target; production code and README remain unchanged.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
