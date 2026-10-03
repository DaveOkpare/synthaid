---
status: accepted
date: 2026-10-02
amends:
  - ADR-0002
  - ADR-0003
  - ADR-0007
  - ADR-0009
---

# Use concrete Agents and recorded Episodes

Superseded by [ADR-0011](0011-remove-plans-and-use-ordinary-task-records.md).
The text below records the intermediate decision before the user removed all
Plans, ToolContext, StepProgress, AgentTool and Runner factories.

The user rejected retaining AgentPlan and the Interaction facade. Agent owns its instruction, model/provider, Tools and Reviewer directly. The Environment owns actual participants and controls conversation order. Episode is the single live accepted-message/event ledger and shared step state, saved as the existing immutable TraceSnapshot.

```text
load/render Seed -> Agent(s) with direct attributes
Environment -> Agent.turn(Episode) -> generate <-> own Review/revise
                                  -> commit -> private Tools -> accepted reply
Episode -> cleanup/seal -> independent final Verification -> publish/export
```

Remove AgentPlan, Interaction, ModelAgent, ScriptedAgent, the Agents mapping wrapper and empty interaction() context. Merge TraceRecorder, StepProgress and Runner's snapshot closure into Episode, with no forwarding aliases. Source Agent declarations remain part of TOML authoring validation; compiled Agent evidence is frozen JSON with the existing saved field names, not a renamed AgentSpec or live configuration owner.

The existing Agent factory keyword now receives the constructed Agent. An explicit custom proposal callback or Agent.generate override supplies drafts; the actual Agent alone controls Review, accepted history and effects. Custom Environment hooks use their owned agents and run(Episode); setup() takes no mapping argument. A dialogue Environment accepts user and assistant Agents directly. Existing task syntax, Provider surfaces and saved Trace formats remain.

Do not delete Tool argument/result validation, private visibility, durable intent before effect, failure/cancellation recording, immutable snapshots or append-only reverification to reach a line-count target. ToolContext remains the external per-call data value, not an additional runtime owner. AgentTool remains an isolated one-shot draft generator under the invoking Agent's reviewed Tool boundary.

Inspiration: verifiers' Environment-controlled user simulation and recorded episode result. This adopts the ownership pattern independently; it does not copy its harness, provisioning, configuration hierarchy, interception or rollout machinery.

- [Env](https://github.com/PrimeIntellect-ai/verifiers/blob/main/verifiers/v1/env.py)
- [Episode](https://github.com/PrimeIntellect-ai/verifiers/blob/main/verifiers/v1/episode.py)
- [UserSimEnv](https://github.com/PrimeIntellect-ai/verifiers/blob/main/verifiers/v1/envs/user_sim/env.py)
