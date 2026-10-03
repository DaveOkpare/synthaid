---
status: superseded
date: 2026-10-03
implementation: pending
superseded_by: ADR-0014
amends:
  - ADR-0011
  - ADR-0012
---

# Taskset-owned quality and a run-only Environment

Superseded by [ADR-0014](0014-use-task-lists-and-task-owned-run-settings.md):
Taskset is a list of Tasks; Tools and quality settings belong to each Task.
The active Taskset proposed below was never implemented.

## Decision

The user accepted the library audit and requested Taskset ownership of both the
per-message critic and final Verifier, taking inspiration from PrimeIntellect.
They initially selected reset/step, then corrected the Environment design to
keep only run(). The latest direction retains whole-conversation execution.

Taskset is the new, concrete domain owner for loading Tasks and defining their
quality policies. Tasks remain ordinary records. Environment executes a complete
conversation and returns its sealed Episode. It owns no final Verifier and does
not grade the completed Episode.

```text
Taskset.load() -> ordinary public Task records
  -> Runner iterates
     -> Environment.run(task) -> sealed Episode
        -> actual Agents propose
           -> Taskset-owned per-message critic -> revise/accept
           -> durable Message Commit -> private Tool effects/results
     -> Taskset.verify(task, episode) -> append final Verification
  -> caller inspection/export
```

The intended Runner loop is:

```python
for task in taskset.load():
    episode = await environment.run(task)
    await taskset.verify(task, episode)
    episodes.append(episode)
```

Taskset owns critic definitions, Rubrics, review instructions and revision policy,
plus the optional final Verifier. Agent remains the enforcement point: it invokes
the borrowed critic and controls revision, acceptance, durable intent and Tool
effects. Defining policy and enforcing it are separate responsibilities. The
existing Reviewer term/contract describes the per-message critic; this decision
does not introduce a second Critic hierarchy.

Taskset.verify applies the final policy to the sealed Episode, retains independent
weighted scoring and persists append-only Verification through the existing
recording implementation. Failed/invalid generation cannot become accepted. A
Taskset with no final Verifier leaves a completed Episode unverified. Cancellation
and judgment/storage failures retain their current evidence and propagation rules.

## Environment interface

Environment is a structural async Protocol with one required execution method:

```python
class Environment(Protocol):
    async def run(self, task: Mapping[str, FrozenJsonValue]) -> Episode: ...
```

Single-Agent, dialogue and custom adapters can share implementation where useful;
implementing the Protocol does not require subclassing a framework base class.
Concrete resource scopes remain explicit, outside Runner's task loop. setup(),
conversation(), agents and output settings are implementation/construction details,
not additional requirements of this Protocol.

run(task) returns after the whole conversation has finished and generation has
been sealed, before final Verification. It continues to include all rounds of a
dialogue in one Episode. No reset/step methods, reward tuple, Gym dependency or
single-agent action-space assumptions are added.

## Taskset and resource discipline

- Taskset supplies public execution input. Reference answers and grading-only
  data stay with Taskset or explicitly private evidence, outside model history.
- Applications/task-file authoring construct Agents with borrowed Taskset-owned
  critic references. Per-task information is ordinary data; no binding context,
  dependency container or replacement Plan is introduced.
- Taskset owns resources it creates for critics/final Verification; Environment
  manages its execution resources. Shared injected Providers have one explicit
  owner and borrowers. Environment does not close a Taskset's quality transport
  by reaching through reviewer.call.provider or verifier.call.provider.
- TaskPackage remains the optional authoring adapter. It prepares Task records
  and constructs a Taskset plus actual execution dependencies. It does not become
  the mandatory runtime Taskset, and compile/validate still create no live owners.
- Historical task syntax and saved run_plan/verification JSON remain readable.
  New Python ownership interfaces replace the old ones explicitly, without aliases.

## Consequences

This amends ADR-0012's Environment-owned final Verification and ADR-0011's
Agent-owned quality configuration. Agent still owns the acceptance mechanism;
Environment still owns conversation control. Runner gains only the explicit call
to Taskset verification after Environment execution; it stays a small task loop.

The audit plan must establish Taskset/Environment contracts before simplifying
their internals. Taskset must earn its place through loading and task-aware quality,
with small interfaces; do not copy upstream config/data/hook hierarchies. Resource
ownership and borrowed critic wiring need concrete constructor designs during
implementation, with the existing cancellation/cleanup tests retained.

The implementation remains pending. Current source and README examples still use
the ADR-0012 interface. See [the revised refactor plan](../../.scratch/library-design-audit/spec.md).

## Sources and adaptation

[PrimeIntellect Tasksets](https://docs.primeintellect.ai/verifiers/v1/tasksets)
load Tasks whose methods define scoring and judging. We adapt that separation by
giving Taskset quality ownership while keeping our Task records ordinary.

[PrimeIntellect Env](https://docs.primeintellect.ai/verifiers/v1/env)
uses a whole-episode run method to control Agents. Our one-method async Protocol
adopts that execution seam with our own Episode return value.

[Gymnasium Env](https://gymnasium.farama.org/api/env/)
defines reset/step transitions, including rewards and separate termination and
truncation. That is a different contract from the run-only design chosen here.
