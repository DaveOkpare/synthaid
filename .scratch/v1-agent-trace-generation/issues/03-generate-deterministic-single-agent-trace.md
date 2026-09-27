# 03: Generate one deterministic single-agent Trace

**What to build:** Let a library or CLI user execute one compiled Seed through a deterministic single Agent in the local Runtime and receive a durable native Trace containing accepted output and execution evidence.

**Blocked by:** 02 — Validate and compile one seeded Task Package

**Status:** resolved

**Type:** implementation

- [x] The canonical asynchronous API and synchronous convenience wrapper can execute a minimal single-agent Task.
- [x] The run command delegates to the same library lifecycle and produces one Trace for the Seed.
- [x] A scripted protocol-faithful Agent receives an Observation and produces an OpenAI-style Message that is committed to the accepted Conversation.
- [x] The native Trace persists the rendered Run Plan, Seed identity and origin, Message Commit, lifecycle Events, timing, termination reason, and component provenance.
- [x] The Run Result contains the Run identity, ordered Trace reference, and terminal status count.
- [x] A fresh execution receives new trace-bound Agent, Environment, recorder, and Conversation state.
- [x] The stored Trace, rather than an in-memory Runner object, is sufficient for native export and inspection by tests.

## Answer

Implemented `Runner.run(TaskPackage)`, asynchronous `generate`, and synchronous
`generate_sync`. Factories create trace-bound Agents and Environments; Environments
receive immutable Task Context and Interaction facades. A `scripted` Agent
supports deterministic CLI execution, with a runnable example under
`examples/scripted-single/`. The thin `run` command forwards Seed and output
overrides to the public lifecycle.

The local store records individual accepted Message Commits and separate Events,
then flushes a complete terminal `trace.json` before publishing its Run index
reference. The snapshot includes the rendered plan, complete Seed, component
references and available source digests, timing, and a distinct generation outcome.
Runs without Verification are `unverified`, including normally terminated Runs.
`load_trace` and `export_native` consume persisted immutable snapshots; exports
require explicit inclusion of unverified or failed statuses.

Evidence: the public Runner tests began red for missing APIs, then passed through
the implementation. Four Runner tests cover persisted execution, fresh Agent and
Environment state across repeated Runs, new identities, native export selection,
and synchronous parity, plus explicit Environment failure classification.
Fourteen CLI tests cover installed entry points,
validation, deterministic generation, override forwarding, and failure exits;
four import-safety tests remain green. Strict mypy and Ruff checks pass. Parent
coordination owns the final full-suite/build checks and series code review.

Scope remains one JSON-object Seed and one single-Agent interaction. Dialogue,
Verification, tools, review, collection processing, provider adapters, and broad
failure/cancellation/persistence hardening belong to subsequent tickets.
