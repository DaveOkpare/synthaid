---
status: accepted
date: 2026-10-02
amends:
  - ADR-0002
  - ADR-0003
  - ADR-0007
  - ADR-0011
---

# Keep Runner as an Environment/task loop

Amended by [ADR-0014](0014-use-task-lists-and-task-owned-run-settings.md) and
[ADR-0015](0015-separate-environment-setup-and-run.md): Taskset is a list of Tasks;
each Task carries its allowed Tools and quality settings. Environment exposes
setup(task) then run(), with final judgment of the accepted Episode history.
Runner remains a task loop. The implementation below remains the current code
checkpoint until that migration is made.

[ADR-0018](0018-runner-owns-the-output-directory.md) adds output_dir and per-execution
path selection to Runner. Episode retains recording; Environment retains execution.

The library was overengineered before the extra machinery was needed. Splitting
Runner into short methods preserved too many responsibilities and barely reduced
its size. The user explicitly narrowed Runner to taking an Environment and tasks
or segments, looping through them and calling the Environment. That is its whole
job. This replaces earlier decisions assigning lifecycle, persistence and final
Verification to Runner; the other ADR-0011 decisions remain accepted.

```text
[Task preparation] -> [ordinary tasks/segments]
                              |
                              v
                    [Runner: iterate and call]
                              |
                              v
                         [Environment]
```

The intended Runner execution is:

```python
for task in tasks:
    await environment.run(task)
```

Task preparation belongs to application code or the optional TaskPackage adapter:
load, parse, validate, render and expand segments before execution. Segments are
ordinary task records; they need no new class. Runner does not interpret task
contents or handle preparation failures.

Environment is initialized with actual Agents and an optional final Verifier.
It owns execution and the lifecycle of its owned resources, and starts an Episode
for a new conversation. One Episode contains the whole conversation, including
multiple user/assistant rounds. Dialogue continues until termination or its round
limit; an Episode is not limited to one user/assistant pair.

Agent owns generation and its own Review before each message is accepted.
Episode/store handle recording and sealing. After the conversation
ends, Environment invokes its optional Verifier to grade the completed Episode's
accepted chat history. Final Verification happens once per completed Episode,
independently of per-message Agent Review. Export remains a caller concern.

Remove per-task Environment/Verifier tuples, `close_each`, copied Runner state,
cleanup flags, error-stage dispatch and persistence/publication machinery from
Runner. Preserve needed execution safeguards with their actual owners. Delete
unused behavior rather than relocating the entire workflow into new wrappers,
contexts, owner types or a generic pipeline. Add capabilities only for a concrete
use. Functions and methods stay at most 20 lines; extra forwarding helpers do not
justify an oversized architecture.

Implemented in ticket [06b](../../.scratch/lean-core-refactor/issues/06b-minimal-runner-and-environment-episodes.md).
Runner has only initialization and the task loop. `Environment.run(task)` creates
an Episode, calls the overridable `conversation(episode)`, seals generation and
then invokes its optional Verifier. Applications use `async with environment`
to close resources after all tasks; Runner does not close them. The task-file
adapter retains Run manifests, indexes, source snapshots and preparation errors.

Retire the unused generic `finalize` hook and unused Episode snapshot override
arguments. Custom per-conversation cleanup belongs in the conversation's own
`finally` block; resource cleanup belongs in Environment's actual scope. Keep
disk-backed Episode recording in this slice rather than adding speculative
storage modes. Task-file users pass `output_dir=` to the adapter instead of a
legacy Runner instance; custom Environments override `conversation`, not `run`.
