# 07: Review Tool calls before executing effects

**What to build:** Let an Agent invoke one assigned function Tool while ensuring the exact Tool-call Message is reviewed and durably accepted before any external effect occurs.

**Blocked by:** 06 — Review and revise conversational Messages

**Status:** ready-for-agent

**Type:** implementation

- [ ] A Tool declares its identifier, description, JSON input schema, optional output schema, and asynchronous call behavior.
- [ ] An Agent may propose a Tool-call Message using the same OpenAI-style Message contract as other proposals.
- [ ] The Tool-call Message is reviewed independently from any later conversational Message.
- [ ] A rejected Tool-call Message is recorded as an Event, never committed, and never executed.
- [ ] An accepted Tool-call Message is committed before arguments are validated and the Tool executes.
- [ ] The validated Tool result is committed as a matching private tool-result Message and becomes visible to the invoking Agent.
- [ ] The other participant cannot observe the private Tool call or result, but can receive the later accepted conversational consequence.
- [ ] The default function adapter follows the same Tool protocol as a custom Tool implementation.
