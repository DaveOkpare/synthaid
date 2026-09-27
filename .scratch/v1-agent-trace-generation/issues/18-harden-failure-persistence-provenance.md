# 18: Harden failure persistence and provenance

**What to build:** Ensure failures at every lifecycle boundary retain the most complete safe Trace possible, clean up resources, preserve causes, and never expose secrets or invent successful data.

**Blocked by:** 11 — Complete Seed sources and package safety; 14 — Add Responses API parity and private reasoning; 16 — Load custom components through explicit references

**Status:** ready-for-agent

**Type:** implementation

- [ ] Configuration, Seed, template, Provider, Agent, Reviewer, Tool, Environment, Runtime, persistence, and Verifier failures are classified at the narrowest recoverable boundary.
- [ ] Failure records include lifecycle stage, Agent, Task Step, proposal or revision attempt, timestamp, and chained cause where available.
- [ ] Accepted Messages committed before a later failure remain durable and ordered; rejected proposals remain Events.
- [ ] Environment and Provider cleanup runs after success, truncation, cancellation, timeout, and failure.
- [ ] A Run-wide source failure stops the Run, while a Trace-specific failure permits later Seeds unless fail-fast is active.
- [ ] Credentials, secret headers, and resolved secret values are absent from persisted plans, metadata, errors, and diagnostic output.
- [ ] Trace snapshots are made durable before their Run index references become visible.
- [ ] No automatic infrastructure retry obscures call counts, timing, cost, or partial effects.
