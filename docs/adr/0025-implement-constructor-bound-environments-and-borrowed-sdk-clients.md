---
status: accepted
date: 2026-10-03
implementation: implemented
amends:
  - ADR-0006
  - ADR-0014
  - ADR-0015
  - ADR-0016
  - ADR-0017
---

# Implement constructor-bound Environments and borrowed SDK clients

The user authorized execution of the seven-module specification, including its
recommended constructor/run boundary and one-Task-per-execution policy.
This resolves the proposals retained in the specification and glossary.

Environment(task, *, client=None) performs local validation. Its async run returns
None, executes ordered segments into Task.episode, seals generation once, and
invokes the optional Task verifier. Async resource preparation occurs inside the
same Task deadline and cleanup scope. There is no public setup or reset operation.
Runner takes Tasks and output_dir, opens each existing Episode by its UUID, creates
one structural Environment per Task, and collects those Episodes. Another sample
constructs another Task. Agents and Judges remain reusable stable definitions.

One Judge constructor serves review and final verification. Judges consume supplied
Messages; revision limits belong to Agent, and verification belongs to Episode.
Deterministic generation-outcome predicates therefore move to application policy;
the loader rejects the former generation_terminated predicate explicitly.

Adopt and pin OpenAI Python SDK 2.30.0 after offline parity at actual Agent/Judge
interfaces. The [SDK](https://github.com/openai/openai-python/tree/v2.30.0) owns wire
types and endpoint calls. Local strict JSON/schema validation, proposal acceptance,
privacy, durable intent, error classification, and stateless history remain ours.
SDK types are revalidated strictly; malformed SDK parsing cannot authorize effects.
Application entry points own and close clients around batches. Calls force zero
retries and do not retain server-side conversation state. No Provider hierarchy or
framework wire-model copies remain.

Tests cover both HTTP surfaces, exact reasoning continuation, ordered effects,
refusal/incomplete/error classification, credential redaction, nested typed schemas,
client precedence, concurrent reuse, private revision feedback, storage failures,
cancellation, historical records, and append-only verification. Optional CLI,
inspection, TUI, launcher, and inert task-file compilation use these same owners.

The [migration guide](../migration-seven-modules.md) records deliberate API changes.
The [implementation report](../../.scratch/library-design-audit/implementation.md)
records final measurements and release verification. Earlier implementation examples
in amended ADRs are historical checkpoints rather than current usage instructions.
