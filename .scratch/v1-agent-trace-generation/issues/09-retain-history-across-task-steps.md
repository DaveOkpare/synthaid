# 09: Retain history across Task Steps

**What to build:** Let a multi-step Task reveal fresh role-specific instructions and Criteria at ordered checkpoints while continuing one accepted Conversation and each Agent's private Tool history.

**Blocked by:** 07 — Review Tool calls before executing effects

**Status:** ready-for-agent

**Type:** implementation

- [ ] A Task may declare ordered, uniquely named Task Steps or omit them entirely for a single-step Task.
- [ ] Each Agent keeps its base instruction while only the current Task Step's instruction addition is active.
- [ ] Current-step Criteria append to the Agent's base Rubric and composed Criterion identifiers remain unique.
- [ ] Previous Task Step instruction and Rubric additions expire when the next step activates.
- [ ] Accepted shared Messages and invoking-Agent-private Tool exchanges remain available across step changes.
- [ ] Step advancement and Task completion use controlled, reviewable actions rather than out-of-band history mutation.
- [ ] The Trace records Task Step activation and associates Messages, Events, and reviews with the active step.
