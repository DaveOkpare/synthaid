# V1 Agent Trace Generation implementation map

- **01 — resolved:** [Bootstrap an executable typed package](issues/01-bootstrap-executable-typed-package.md#answer).
  The installed CLI, locked uv workflow, typing metadata, and CI checks are in
  place. See [development commands](../../README.md#development) for setup and
  verification.
- **02 — resolved:** [Validate and compile one seeded Task Package](issues/02-validate-compile-seeded-task.md#answer).
  A strict single-Agent JSON compiler and model-free `validate` command now
  produce immutable Run Plans with stable digests. See
  [validation usage](../../README.md#validate-a-task-package) and the
  [example package](../../examples/single-agent/task.toml). Compilation and
  rendering are now exercised through ticket 03's agreed Runner seam.
- **03 — resolved:** [Generate one deterministic single-agent Trace](issues/03-generate-deterministic-single-agent-trace.md#answer).
  The asynchronous Runner, synchronous wrapper, scripted `run` CLI, fresh
  trace-bound component factories, durable Message Commits and complete native
  snapshots are implemented. Persisted Trace inspection and status-selected
  native export need no live Runner. See [generation usage](../../README.md#generate-a-trace)
  and the [scripted example](../../examples/scripted-single/task.toml).

- **04 — resolved:** [Generate and export a two-agent dialogue](issues/04-generate-export-two-agent-dialogue.md#answer).
  Either generic participant may initiate or be the explicit target. Dialogue
  relays accepted references, retains full shared history, and distinguishes
  accepted completion from round/timeout truncation. Target-oriented OpenAI
  JSONL export and the thin export CLI read complete persisted snapshots and
  require explicit selection of non-accepted statuses. See
  [dialogue generation and export](../../README.md#generate-and-export-a-dialogue)
  and the [scripted dialogue package](../../examples/scripted-dialogue/task.toml).

Tickets 05–19 remain unimplemented.
