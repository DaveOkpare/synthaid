# 17: Inspect recorded Runs and Traces

**What to build:** Let an operator understand recorded Runs and Traces without loading transient Runner state or mutating generation artifacts.

**Blocked by:** 09 — Retain history across Task Steps; 10 — Run deterministic JSON and JSONL Seed collections; 14 — Add Responses API parity and private reasoning

**Status:** ready-for-agent

**Type:** implementation

- [ ] The inspect command renders a concise non-interactive Run or Trace summary from persisted data.
- [ ] A simple terminal UI can navigate accepted Conversation, participant projections, private Tool activity, review attempts, Verification attempts, provenance, failures, and artifacts.
- [ ] Task Step boundaries and review-exhausted Messages are visible.
- [ ] Reasoning presence and retention policy are visible without exposing suppressed reasoning text.
- [ ] Collection summaries report ordered Trace references and counts for invalid, failed, unverified, rejected, and accepted statuses.
- [ ] Inspection does not rewrite, reverify, resume, or otherwise mutate the selected Run or Trace.
- [ ] Rendering and navigation are tested against recorded fixtures without pixel-level snapshots.
