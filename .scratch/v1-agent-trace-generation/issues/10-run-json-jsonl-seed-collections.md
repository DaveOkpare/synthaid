# 10: Run deterministic JSON and JSONL Seed collections

**What to build:** Let an operator run a Task over every Seed in a JSON or JSONL source and receive one isolated, indexed Trace per Seed with deterministic ordering and collection-level status counts.

**Blocked by:** 03 — Generate one deterministic single-agent Trace; 05 — Verify and reverify sealed Traces

**Status:** ready-for-agent

**Type:** implementation

- [ ] A JSON object yields one Seed, a JSON array yields one Seed per element, and JSONL yields one Seed per non-empty record.
- [ ] Seed enumeration order is deterministic and each valid Seed compiles to an independent immutable Run Plan.
- [ ] A configured Variable may supply a stable Seed ID; otherwise a canonical content hash supplies it.
- [ ] Duplicate Seed IDs within one Run are rejected without conflating Seed identity and Trace-attempt identity.
- [ ] Invalid, failed, unverified, rejected, and accepted attempts are represented in the Run index and aggregate counts.
- [ ] A Seed-specific failure does not stop later Seeds by default, while fail-fast stops after the first qualifying failure.
- [ ] Each Trace is durably finalized before the Runner advances to the next Seed.
- [ ] No accepted history or trace-bound mutable state leaks between Seeds.
