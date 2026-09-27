# 02: Validate and compile one seeded Task Package

**What to build:** Let a task author validate a minimal single-step Task Package against one JSON Seed and compile it into an immutable, serializable, secret-scrubbed Run Plan without invoking a model.

**Blocked by:** 01 — Bootstrap an executable typed package

**Status:** ready-for-agent

**Type:** implementation

- [ ] A Task Package with one Agent instruction, one explicit Target Agent, local Runtime configuration, Variables, and one JSON Seed loads successfully.
- [ ] Dot-path Variables resolve against nested Seed data and strict Jinja rendering produces the Agent's per-Seed instruction.
- [ ] Missing Variables, invalid selectors, malformed configuration, duplicate identifiers, or target cardinality other than one fail before component construction.
- [ ] The resulting Run Plan distinguishes Task, Seed, Trace-attempt inputs, Agent, Environment, and Runtime configuration and has a stable digest.
- [ ] Resolved secret values and live runtime objects are absent from serialized Run Plan data.
- [ ] The validation command reports success or a precise validation failure and performs no model call.
