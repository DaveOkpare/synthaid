---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
supersedes:
  - ADR-0013
amends:
  - ADR-0011
  - ADR-0012
---

# Use Task lists and Task-owned run settings

The Environment interface and lifecycle below are amended by
[ADR-0015](0015-separate-environment-setup-and-run.md): use setup(task) then run(),
with no reset or step methods. Taskset-as-list and Task-owned settings remain.

[ADR-0019](0019-task-owned-episodes-span-segments.md) makes Episode Task-owned,
shared across ordered segments; Environment executes into it through setup/run.

[ADR-0021](0021-declare-tools-on-each-agent.md) moves Tool declarations to each
Agent definition. The Task-level Tool list below is superseded.

## Decision

Taskset is simply a list of Tasks. Each Task declares the Tools available during
that execution and its per-message and per-episode quality settings: Rubrics,
judge/critic configuration or prompts, and any associated revision policy.
Taskset has no load, verify, binding or cleanup methods. This replaces
ADR-0013's proposed active Taskset owner with the user's clarified data model.

Task is a plain execution record, without framework inheritance or required
methods. It contains public input, Agent definitions/settings, available Tools,
message-review settings and episode-verification settings, with existing
identity/origin evidence. Concrete
field names and the choice of a mapping or one plain data class belong to the
first implementation slice; no TaskData/TaskConfig hierarchy is introduced.

```text
application or optional TaskPackage -> list of Tasks
  -> Runner iterates
     -> Environment.run(task)
        -> reset state and create a fresh Episode
        -> set up Agents, Tools and quality adapters from the Task
        -> repeat internal steps until completion or the execution limit
        -> actual Agents use this Task's Tools and message critic
        -> accepted intent is durably committed before Tool effects
        -> generation is sealed
        -> this Task's episode judge appends final Verification
        -> recorded Episode returned
```

The Runner loop remains:

```python
for task in taskset:
    episodes.append(await environment.run(task))
```

Environment is a structural async Protocol with one required method:

```python
class Environment(Protocol):
    async def run(self, task: Task) -> Episode: ...
```

run(task) sets up and executes a whole conversation. Agent remains the per-message
acceptance mechanism, using that Task's critic before committing output or executing Tools.
Environment invokes the Task's final Verifier after sealing generation, using the
existing append-only recording. Neither Agent nor Environment is the source of
the Task's quality policy. No taskset-level verification call is added to Runner.

## Internal lifecycle

The run-only interface contains the reset/setup and step lifecycle. A caller does
not have to construct the Task's Agents and reviewers, reset the Environment, or
drive individual steps before calling run(task).

1. Start fresh execution state and recording for the Task.
2. Read its participant definitions, instructions/model settings, allowed Tools,
   critic prompts/configuration/Rubrics and final-judge settings. Construct and
   initialize the actual Agents and quality adapters for this execution.
3. Advance the internal conversation loop until completion, truncation or failure.
   Each step uses Agent's existing review/acceptance/effects mechanism.
4. Seal generation, apply the Task's optional final judge and return the Episode.
5. Release resources created for this execution in finally, including partial
   setup, step or judging failure and cancellation. Shared borrowed resources
   retain their outer lifetime.

These are implementation phases, not additional Protocol methods or required
subclass hooks. Private setup/step operations may be useful, but the design does
not require a generic state machine, a new context object or a Gym dependency.
Environment construction can accept shared infrastructure such as Providers and
output settings; the current Task determines its participants and quality policy.
Mutable conversation and review state must be fresh for each call.

## Execution and data discipline

- Only Tools made available by the current Task may be advertised or called.
  Allowed Tool sets and review settings must not carry over between Tasks or
  interfere with concurrent Episodes. Preserve participant-specific assignment.
- A Task's public input is projected explicitly into observations. Judge prompts,
  reference answers and other grading-only data do not automatically become
  model-visible. Carrying execution settings does not expose the entire Task.
- Available Tools can be actual Tool references in direct Python use or authored
  declarations resolved before execution. Runtime references are not JSON data;
  persist their ordinary declarations/evidence, rather than freezing or
  serializing the whole runtime Task as JSON.
- Task declares settings; it does not own live transports or resource lifetimes.
  Environment owns resources it creates during setup; application scopes own
  shared resources they inject, with shared Tools and Providers borrowed.
  A list of Tasks is not a resource owner.
- TaskPackage remains optional. Parsing and compilation produce inert ordinary
  data and prepare Tasks for run(task); Environment performs runtime participant
  and critic setup from those Tasks. Preserve task-file syntax, provenance and
  historical saved Trace JSON. Preparation does not preconstruct Agents or judges
  or patch an Environment's participants before execution.
- Failed/invalid generation cannot be promoted by final grading. A completed
  Episode without a final judge remains unverified. Keep cancellation, deadlines,
  durable intent, private history and independent append-only reverification.

## Consequences

This retains ADR-0012's small Runner and Environment execution/verification
sequence, while replacing permanent Agent/Environment quality configuration with
Task-local settings and keeping the Environment's required interface to run().
It amends ADR-0011's JSON-only execution-input assumption where a Task contains
actual Tool references; serialized authoring records remain ordinary JSON data.

The implementation is pending. Current source and README still describe the
ADR-0012 checkpoint. The [refactor plan](../../.scratch/library-design-audit/spec.md)
must establish the Task record and Environment's per-run setup before simplifying
the existing internals. No taskset.py owner or new loading/configuration framework
is required by this decision.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
