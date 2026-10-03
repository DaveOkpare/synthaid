---
status: accepted
date: 2026-10-01
amends:
  - ADR-0002
  - ADR-0003
---


> [ADR-0010](./0010-use-concrete-agents-and-recorded-episodes.md) replaces the runtime interfaces below with concrete Agent ownership, direct Environment scheduling and recorded Episodes; removed names have no aliases.
# Give each Agent runtime its own Review and keep the core lean

> Amended by [ADR-0008](./0008-use-shared-http-transports-and-optional-vllm-startup.md): compatible endpoints use the shared HTTP transports; mandatory certification gates and conformance-only entry points are retired.

> [ADR-0009](./0009-remove-unused-import-compatibility.md) supersedes blanket import preservation: unused compatibility paths are removed.

Implementation is pending the staged [refactor](../../.scratch/lean-core-refactor/spec.md). This decision changes internal ownership, not the public Python or Task Package interfaces.

Task 05 implements the single owner using the existing `Interaction` class.
`AgentHandle` is removed; `Agents[id].interaction(task)` yields that same
Interaction. The existing acceptance loop already owns Review and Tools, so
consolidation needs no renamed runtime, compatibility alias, or extra module.
Runner dependency assembly is handled separately in Task 06.

ADR-0002 made `Interaction.turn()` the acceptance boundary. The implementation splits the runtime between `AgentHandle`, `Interaction`, and Runner construction. That split obscures which Agent owns Review and makes changes cross several layers. Each Agent needs one runtime that owns its complete turn; the Runner's final Verification remains a separate decision.

## Decision

```text
Runner: compile Seed -> construct fresh runtime -> manage Trace lifecycle
  |
  +-- Environment: schedule Agent turns and Task Steps
  |     |
  |     +-- Agent runtime: observe -> generate -> Review <-> revise
  |                              -> commit -> private Tools -> accepted reply
  |
  +-- seal generation -> final Verification -> publish Trace
```

- One per-Agent runtime owns observation projection, generation, its Reviewer, revision budgets, private Tool execution, and accepted replies. It receives the framework recorder; it does not create a separate storage system.
- Environments retain ordinary Python control flow. `Agents[id].interaction(task)` and the resulting `turn()` and `control()` hooks reach that same runtime. Compatibility wrappers contain no alternate turn implementation.
- Custom `Agent.generate(observation)` implementations remain proposal producers. They do not have to implement Review, private history, or persistence. Reviewer, Tool, Provider, and factory contracts remain unchanged.
- The Runner owns Seed iteration, fresh per-Trace construction, timeout/cancellation/cleanup, sealing, and publication. It invokes the final Verifier on the completed Trace. Review authorizes a message; Verification decides completed-Trace quality and default export eligibility.
- Task loading/compilation remains separate from runtime state. Preserve ADR-0003's immutable, rendered, secret-scrubbed Run Plan. Raw-data preparation remains ordinary Python producing `seeds=` records.
- Keep one implementation per responsibility. Preserve existing exports, documented imports, constructors, factory overrides, Task syntax/defaults, CLI behavior, and saved formats through thin forwards where necessary.
- Responses and Chat Completions remain core Provider surfaces under ADRs 0005–0006. Isolate vLLM execution/conformance and the terminal UI into integration/UI namespaces in the same distribution. Existing entry points still work; separate installation is a later compatibility decision.

ADR-0004's effect and durability rules remain binding: apply configured Review to every model-produced message before acceptance; commit approved Tool intent before execution; validate and commit results afterward. Tools and their results remain private to the invoking Agent. Rejected drafts remain Events. Revision exhaustion cannot authorize a rejected Tool call or Task control. Weighted rubrics, current-step additions, durable partial failed Traces, accepted-only default export, and append-only reverification remain unchanged.

## Considered Options

- **Rename `Interaction` without consolidating ownership.** Leaves the duplicated runtime boundary and maintenance cost.
- **Require custom Agents to implement a new `turn()` API.** Breaks extensions and makes each author rebuild Review and persistence.
- **Move Review into the Environment or Runner.** Separates an Agent's acceptance policy from its turn and mixes message Review with final Verification.
- **Remove integrations or redesign Task files immediately.** Conflicts with the agreed compatibility constraint. Isolation comes before any packaging change.

## Consequences

Agent turns become the single place to change Review, revision, private history, and Tools. The Runner and Environment can shrink without weakening durable evidence. Compatibility limits deletion: old names may remain, but implementation is shared. Count relocation separately from deletion and keep failure-handling tests even when line-count targets become harder.

## References

- [ADR-0002: Environment and Interaction](0002-use-run-based-dialogue-environments.md)
- [ADR-0003: immutable per-Seed Run Plans](0003-compile-one-run-plan-per-seed.md)
- [ADR-0004: Review before effects and durable Traces](0004-review-model-messages-before-effects-and-export-complete-traces.md)
- [ADR-0005: Provider boundary and vLLM](0005-use-an-openai-shaped-provider-protocol-with-vllm-conformance.md)
- [ADR-0006: API surfaces and structured outputs](0006-support-responses-and-chat-completions-with-pydantic-structured-outputs.md)
- [Interface sketch](../../.scratch/lean-core-refactor/interfaces.md)
- [Compatibility baseline](../../.scratch/lean-core-refactor/baseline.md)
