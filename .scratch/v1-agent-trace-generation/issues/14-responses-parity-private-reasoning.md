# 14: Add Responses API parity and private reasoning

**What to build:** Let the OpenAI Provider use Responses by default while preserving the same Agent, Tool, Reviewer, Verifier, and Trace semantics as Chat Completions.

**Blocked by:** 07 — Review Tool calls before executing effects; 13 — Use Pydantic structured outputs for quality gates

**Status:** ready-for-agent

**Type:** implementation

- [ ] Each Provider Plan selects Responses or Chat Completions explicitly and the selected surface is immutable and recorded in provenance.
- [ ] The OpenAI Provider defaults to Responses and never silently falls back to Chat Completions.
- [ ] Complete accepted history is translated to self-contained Responses input with provider storage disabled by default.
- [ ] Authoritative Conversation state never depends on a provider response identifier.
- [ ] Responses text, function calls, function-call outputs, refusals, incomplete states, usage, and native identifiers normalize to framework models.
- [ ] Equivalent requests through both surfaces produce semantically equivalent Messages and parsed values in contract tests.
- [ ] Returned reasoning remains participant-private Event data, is never relayed or inserted into Conversation, and is excluded from default training export.
- [ ] A policy may suppress full reasoning text while retaining presence and usage metadata.
- [ ] Provider-hosted Tools remain unsupported because they can bypass review-before-effect.
