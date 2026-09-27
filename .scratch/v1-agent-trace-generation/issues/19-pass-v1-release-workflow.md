# 19: Pass the complete V1 release workflow

**What to build:** Demonstrate that the assembled framework can produce a verified, inspectable, exportable Dataset from a representative multi-Seed, multi-step, Tool-using dialogue and satisfy every repository release gate.

**Blocked by:** 15 — Add tested vLLM Provider profiles; 17 — Inspect recorded Runs and Traces; 18 — Harden failure persistence and provenance

**Status:** ready-for-agent

**Type:** implementation

- [ ] One deterministic end-to-end fixture runs multiple Seeds through a multi-step user–assistant dialogue with one Target Agent.
- [ ] The fixture includes a rejected and revised conversational Message, a rejected Tool call that never executes, an accepted private Tool exchange, and retained cross-step history.
- [ ] The Run contains accepted, rejected, unverified, invalid, or failed examples sufficient to prove status accounting and explicit export inclusion rules.
- [ ] Final Verification, reverification, native export, accepted-only OpenAI JSONL export, static inspection, and TUI inspection all operate on persisted Trace snapshots.
- [ ] The public asynchronous API, synchronous wrapper, and CLI commands share one lifecycle and produce consistent results.
- [ ] Importing the package and collecting tests perform no network access, model initialization, or storage mutation.
- [ ] Locked dependency validation, Ruff lint, Ruff format checking, the deterministic pytest suite, CLI smoke tests, and source/wheel building all pass.
- [ ] User-facing documentation explains the first successful validate, run, inspect, export, and reverify workflow without promising out-of-scope features.
