# 04: Generate and export a two-agent dialogue

**What to build:** Let a task author run a generic user–assistant dialogue in which the configured initiator sends the first Message, participants alternate accepted replies, and the resulting Conversation can be projected from the sole Target Agent's perspective.

**Blocked by:** 03 — Generate one deterministic single-agent Trace

**Status:** ready-for-agent

**Type:** implementation

- [ ] The built-in dialogue Environment requires generic user and assistant participants and exactly one explicit Target Agent.
- [ ] The configured initiator produces the opening Message and the Environment alternates participants without a declarative turn graph.
- [ ] Both Agents receive the full accepted shared Conversation in canonical occurrence order.
- [ ] Legitimate completion is distinguished from maximum-round or timeout truncation.
- [ ] The persisted Trace contains one shared Conversation without duplicate Messages when replies are relayed.
- [ ] OpenAI-style JSONL projection maps Target Agent output to assistant Messages and the other participant's shared output to user Messages.
- [ ] Non-accepted status export requires an explicit option until final Verification is available.
