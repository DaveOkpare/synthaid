---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0012
  - ADR-0014
---

# Separate Environment setup and run

[ADR-0016](0016-build-seven-directly-usable-generation-modules.md) retains this
setup/run sequence and narrows the core to seven directly usable modules. Its
public Environment is concrete; custom implementations satisfy the same interface.

[ADR-0017](0017-use-agent-reviewers-task-verifiers-and-independent-episodes.md)
clarifies fresh participant setup and independent Episode output per run, with
reviewer on each Agent definition and verifier on Task.

[ADR-0018](0018-runner-owns-the-output-directory.md) puts output_dir on Runner and
adds the per-execution episode_path keyword to setup. The two-method lifecycle
below remains; its original recording-path wiring is amended.

[ADR-0019](0019-task-owned-episodes-span-segments.md) attaches Episode to Task,
restores setup(task) without a path keyword, and makes run return None after
executing that Task's segments into its Episode. The original result contract
below is historical; the setup/run lifecycle remains.

## Decision

Environment exposes setup(task) and run(). Taskset remains a list of plain Tasks,
with participant definitions, allowed Tools and per-message/per-episode quality
settings on each Task. This amends ADR-0014's run(task)-only interface.

```python
class Environment(Protocol):
    async def setup(self, task: Task) -> None: ...
    async def run(self) -> Episode: ...
```

setup(task) starts fresh execution state and recording, constructs/configures the
Task's actual Agents, Tools, reviewers and final judge, and initializes their
public input. Shared infrastructure may be injected into Environment; participant
and quality choices come from the Task. Partial setup failure releases resources
created so far and retains the existing failure evidence.

run() executes the prepared conversation. Agent enforces per-message Review
before acceptance or Tool effects. Environment seals generation, supplies the
Episode's accepted history to the Task's optional final judge, appends final
Verification and returns the recorded Episode. Rejected drafts are not accepted
history. Cleanup releases execution-owned resources on success, failure or
cancellation; shared borrowed resources retain their outer lifetime.

There are no reset or step methods, public or private. Conversation scheduling
remains ordinary iteration inside run(), with meaningful private operations where
needed. No lifecycle framework or new run-context wrapper is introduced.

Runner still performs only per-Task iteration:

```python
for task in taskset:
    await environment.setup(task)
    episodes.append(await environment.run())
```

Each successful setup/run pair is one execution with a fresh Episode. Reuse an
Environment sequentially; concurrent executions use separate Environment
instances and explicitly shared dependencies. run() requires successful setup
for that execution. TaskPackage prepares Task data, not live participants or
patched Environments. Historical Trace data and append-only reverification remain
readable and unchanged by this design.

## Diagram convention

The previous diagram mixed configuration dependencies and execution flow, making
it appear that Agents fed data back into Tasks. The replacement shows execution
order only: Taskset -> Runner -> setup(task) -> run() -> accepted Episode history
-> final judge -> recorded Episode/Verification. Task configuration is described
in prose. Provider/Tool dependencies do not become extra Task nodes in that flow.

## Consequences

The Environment interface has two methods and one ordering rule. Runner gains
only the setup call, without reading Task contents or owning judges. Final
judgment input is the accepted Episode history, not a Task configuration node.
No final judge leaves completion unverified; failed/invalid generation cannot be
promoted. Existing recording, privacy, cancellation and cleanup guarantees remain.

Implementation is pending. The [refactor plan](../../.scratch/library-design-audit/spec.md)
and domain glossary describe this target; current source and README still use
ADR-0012's implementation checkpoint.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
