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

- **05 — resolved:** [Verify and reverify sealed Traces](issues/05-verify-reverify-sealed-traces.md#answer).
  Weighted Boolean Verification now runs after durable generation sealing, records
  immutable versioned attempts, and preserves all generation bytes on reverification.
  Snapshot inspection and exports select the latest or an explicit valid decision,
  retain earlier valid eligibility after judge errors, and preserve generation
  failures. Shared scoring is ready for ticket 06. See
  [verification usage](../../README.md#verify-and-reverify-traces) and the
  [offline verified example](../../examples/verified-single/task.toml).

- **06 — resolved:** [Review and revise conversational Messages](issues/06-review-revise-conversational-messages.md#answer).
  Each Agent may use a fresh Reviewer with stable rendered instructions and a
  weighted Rubric. Per-Message review, private revision feedback, exact rejected
  proposal Events, explicit conversational exhaustion fallback, and linked review
  evidence now guard commits and completion. Initial and revised list Actions
  retain independent Message budgets. See
  [review usage](../../README.md#review-and-revise-messages) and the
  [offline reviewed dialogue](../../examples/reviewed-dialogue/task.toml).

Tickets 07–19 remain unimplemented.
