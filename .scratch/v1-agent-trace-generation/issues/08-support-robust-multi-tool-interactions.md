# 08: Support robust multi-Tool interactions

**What to build:** Let Tool-capable Agents complete ordered multi-call workflows while preserving accepted intent, validated results, failures, privacy, and partial progress as durable Trace data.

**Blocked by:** 07 — Review Tool calls before executing effects

**Status:** ready-for-agent

**Type:** implementation

- [ ] A Message containing multiple Tool calls is reviewed once in the exact structure produced by the model.
- [ ] Accepted calls execute sequentially in declared order and retain stable call identifiers.
- [ ] Each Tool result is validated and committed separately in canonical occurrence order.
- [ ] Tool execution failure is represented as a typed Tool result when the Tool contract supports it, otherwise the Trace fails with a typed reason.
- [ ] A crash or later rejection can leave a valid partial Conversation ending in an accepted Tool call or result without rolling it back.
- [ ] Revision exhaustion never force-accepts a Tool-call or control-action Message.
- [ ] An Agent-wrapped Tool adapter can expose a subordinate Agent through the same Tool contract.
- [ ] Target-oriented export includes only the Target Agent's private Tool exchanges and preserves matching call identifiers.
