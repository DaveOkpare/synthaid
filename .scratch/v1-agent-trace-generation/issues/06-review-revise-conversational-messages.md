# 06: Review and revise conversational Messages

**What to build:** Let a task author enable an Agent Reviewer that evaluates each conversational Message proposal against a weighted Rubric and prevents rejected drafts from entering accepted history or reaching another participant.

**Blocked by:** 04 — Generate and export a two-agent dialogue

**Status:** ready-for-agent

**Type:** implementation

- [ ] Review can be enabled independently for each Agent and uses stable Reviewer instructions plus the Agent's active Rubric.
- [ ] The Reviewer returns one Boolean per Criterion plus feedback, while the framework validates the mapping and computes the normalized score.
- [ ] A below-threshold proposal is recorded as an Event, excluded from the Conversation, and revised with Reviewer feedback.
- [ ] Maximum revisions count additional proposals after the initial rejection and apply the full review boundary to every revision.
- [ ] Only an accepted conversational Message is committed and relayed to the other Agent.
- [ ] Revision exhaustion truncates by default; explicit fallback may accept only a conversational Message and marks it review-exhausted.
- [ ] Malformed Reviewer output cannot commit a Message.
