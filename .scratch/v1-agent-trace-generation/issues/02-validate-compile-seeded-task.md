# 02: Validate and compile one seeded Task Package

**What to build:** Let a task author validate a minimal single-step Task Package against one JSON Seed and compile it into an immutable, serializable, secret-scrubbed Run Plan without invoking a model.

**Blocked by:** 01 — Bootstrap an executable typed package

**Status:** resolved

**Type:** implementation

- [x] A Task Package with one Agent instruction, one explicit Target Agent, local Runtime configuration, Variables, and one JSON Seed loads successfully.
- [x] Dot-path Variables resolve against nested Seed data and strict Jinja rendering produces the Agent's per-Seed instruction.
- [x] Missing Variables, invalid selectors, malformed configuration, duplicate identifiers, or target cardinality other than one fail before component construction.
- [x] The resulting Run Plan distinguishes Task, Seed, Trace-attempt inputs, Agent, Environment, and Runtime configuration and has a stable digest.
- [x] Resolved secret values and live runtime objects are absent from serialized Run Plan data.
- [x] The validation command reports success or a precise validation failure and performs no model call.

## Answer

Implemented `TaskPackage.load(...).compile(...)`, strict typed TOML validation,
nested JSON Variable selectors, sandboxed Jinja rendering, immutable Run Plans,
canonical digests, Seed provenance, model defaults and overrides, and the thin
`agentinstruct validate` command with text and JSON results. Provider declarations
retain credential references without resolving secrets or constructing clients.
Run and Trace IDs remain execution-owned; the plan contains inputs for one attempt.

The [single-agent example](../../../examples/single-agent/task.toml) and
[README](../../../README.md#validate-a-task-package) document the supported slice.
Collections, multi-step Tasks, execution, adapters, and comprehensive package
safety remain assigned to their existing tickets.

Validation: all 14 CLI/import-safety tests, strict Mypy, Ruff lint/format,
lockfile consistency, and source/wheel builds passed on Python 3.13.3.
The audit test confirms validation performs no network calls, provider imports,
or filesystem writes. Automated tests use the pre-agreed CLI/import boundaries;
dedicated compiler API tests were not added while confirmation of that new seam
was pending. The future Runner lifecycle remains the spec's primary acceptance
seam.

The two-axis review found and fixed nondeterministic runtime-object interpolation
in templates; read-only review exercises confirmed deterministic output for
ordinary filters and loops and rejection of method coercion. No ticket-2 Spec
findings remain. The Standards review's portable-filename finding is deferred to
ticket 11, which explicitly owns that requirement.
