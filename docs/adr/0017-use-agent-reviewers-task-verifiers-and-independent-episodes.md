---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0014
  - ADR-0015
  - ADR-0016
---

# Use Agent reviewers, Task verifiers and independent Episodes

[ADR-0018](0018-runner-owns-the-output-directory.md) assigns output_dir and unique
Episode path selection to Runner, without changing the review or isolation rules.

[ADR-0019](0019-task-owned-episodes-span-segments.md) makes Episode Task-owned and
shared across its ordered segments. Isolation now applies between Task executions;
the optional Agent reviewer and Task verifier settings remain.

[ADR-0021](0021-declare-tools-on-each-agent.md) puts tools alongside reviewer on
each Agent definition, replacing the Task-level tools field in the example below.

The [refactor spec](../../.scratch/library-design-audit/spec.md#reusable-judge-constructor)
makes the shared evaluation mechanism explicit: Agent.reviewer and Task.verifier
accept the same Judge constructor and can reuse one suitable instance. Judge
holds no Episode/revision/history state; the caller determines invocation timing.

## Decision

[ADR-0022](0022-construct-agent-definitions-and-revise-from-review.md) makes the
feedback loop explicit: reviewer supplies guidance and Agent authors a revised
proposal. [ADR-0023](0023-use-agent-directly-and-keep-execution-state-local.md)
supersedes its separate definition constructor and the fresh runtime Agent rule
below; execution state is isolated in Episode and local calls instead.

Each Agent definition/configuration has an optional reviewer, defaulting to None.
It specifies that Agent's message critic: prompt/Rubric, model or callable
evaluation settings and revision policy. Different Agents may use different
reviewers, and an Agent can run without one. There is no message_judge field on
Task and no task-wide message critic automatically assigned to all participants.

Task has an optional verifier field for final Episode judgment. This replaces
the proposed episode_judge name. Environment prepares the verifier from Task
information and applies it to the completed Episode's sealed accepted history.
Judge remains the shared evaluation mechanism in judge.py; naming the roles
reviewer and verifier does not require extra wrappers or modules.

```text
Task
  agents
    assistant: instruction/model/settings + optional reviewer
    other participant: instruction/model/settings + optional reviewer
  tools
  verifier: optional final accepted-history judge
```

setup(task) prepares fresh participants and execution state. run() builds and
returns one independent Episode, the output of that Environment execution.
Runner.run() loops over Tasks and returns a list of these separate results; it
does not combine their conversations into one Episode.

Repeating the same Task still creates another Episode. Accepted messages,
drafts/events, Tool-call/result state, reviewer feedback/revision counts and
verification records cannot carry over implicitly. Later setup/run pairs cannot
mutate an already returned Episode or its read-only messages. A continuing
conversation must be explicitly supplied as input to another Task.

Injected clients and Tool capabilities may be shared under their declared
ownership; sharing infrastructure does not share Episode/Agent conversation
state. Concurrent executions use separate Environment instances. Setup failure
and cancellation retain the recording/cleanup guarantees of the existing plan.

An absent reviewer skips model/callable review for that Agent while keeping local
validation, Tool assignment and durable acceptance rules. An absent verifier
leaves completion unverified. Failed/invalid generation cannot be promoted by
final judgment; final decisions remain append-only.

## Consequences

The active configuration names are agents[id].reviewer and Task.verifier, with
no message_judge/episode_judge aliases. Episode is execution output rather than
Task configuration or a shared batch history. The domain term Run now means one
prepared Environment execution; historical adapter run manifests/IDs remain
readable as stored batch metadata, without a core Run-owner class.

Implementation remains unstarted. The [refactor plan](../../.scratch/library-design-audit/spec.md)
and glossary describe this target; source and README are not rewritten to claim
it is already available.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
