# 03: Generate one deterministic single-agent Trace

**What to build:** Let a library or CLI user execute one compiled Seed through a deterministic single Agent in the local Runtime and receive a durable native Trace containing accepted output and execution evidence.

**Blocked by:** 02 — Validate and compile one seeded Task Package

**Status:** ready-for-agent

**Type:** implementation

- [ ] The canonical asynchronous API and synchronous convenience wrapper can execute a minimal single-agent Task.
- [ ] The run command delegates to the same library lifecycle and produces one Trace for the Seed.
- [ ] A scripted protocol-faithful Agent receives an Observation and produces an OpenAI-style Message that is committed to the accepted Conversation.
- [ ] The native Trace persists the rendered Run Plan, Seed identity and origin, Message Commit, lifecycle Events, timing, termination reason, and component provenance.
- [ ] The Run Result contains the Run identity, ordered Trace reference, and terminal status count.
- [ ] A fresh execution receives new trace-bound Agent, Environment, recorder, and Conversation state.
- [ ] The stored Trace, rather than an in-memory Runner object, is sufficient for native export and inspection by tests.
