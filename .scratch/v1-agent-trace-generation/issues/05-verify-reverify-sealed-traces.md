# 05: Verify and reverify sealed Traces

**What to build:** Let a dataset producer evaluate a sealed Trace with weighted Boolean Criteria, derive its quality status, export accepted data by default, and append later Verification attempts without regenerating the Conversation.

**Blocked by:** 03 — Generate one deterministic single-agent Trace

**Status:** ready-for-agent

**Type:** implementation

- [ ] Deterministic code Verifiers and LLM-judge-shaped fakes implement one asynchronous protocol over an immutable Trace snapshot.
- [ ] Each declared Criterion has a unique identifier and positive finite weight, and the framework computes passing weight divided by total weight.
- [ ] A valid score at or above the inclusive threshold produces accepted status; a lower valid score produces rejected status.
- [ ] Missing, duplicate, unknown, or non-Boolean verdicts and Verifier execution failures produce unverified status rather than false Criteria.
- [ ] Each Verification attempt is immutable and versioned, and reverification does not change accepted Conversation bytes.
- [ ] Default OpenAI-style export includes only accepted Traces; other terminal statuses require explicit inclusion.
- [ ] Reviewer and Verifier scoring logic is shared where appropriate without merging their lifecycle responsibilities.
