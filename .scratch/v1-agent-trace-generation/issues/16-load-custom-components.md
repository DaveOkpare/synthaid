# 16: Load custom components through explicit references

**What to build:** Let extension authors run a complete Task using built-in short identifiers or explicit Python references for custom Agents, Environments, Tools, Reviewers, and Verifiers without bypassing framework invariants.

**Blocked by:** 05 — Verify and reverify sealed Traces; 08 — Support robust multi-Tool interactions; 09 — Retain history across Task Steps

**Status:** ready-for-agent

**Type:** implementation

- [ ] Built-in components resolve through a small explicit registry and custom components resolve through explicit import references.
- [ ] Resolution is lazy, validates the required public protocol immediately, and reports the exact failing reference.
- [ ] An explicit lookup failure never silently falls back to a similarly named built-in.
- [ ] A custom Environment receives only the narrow immutable Task Context and run-bound Agent facades.
- [ ] A custom Environment can orchestrate a multi-party interaction in ordinary asynchronous Python without direct recorder or Provider access.
- [ ] Custom Tools, Reviewers, and Verifiers retain the same review, privacy, persistence, and scoring guarantees as built-ins.
- [ ] One fixture Task demonstrates a custom Environment and at least one other custom component through validation, execution, Verification, and persisted Trace output.
