---
status: accepted
date: 2026-10-02
supersedes:
  - ADR-0010
amends:
  - ADR-0002
  - ADR-0003
  - ADR-0007
  - ADR-0009
---

# Remove Plans and use ordinary task records

Runner ownership is further narrowed by [ADR-0012](0012-keep-runner-as-an-environment-task-loop.md).
The decisions below remain historical context where that amendment changes them.

[ADR-0019](0019-task-owned-episodes-span-segments.md) restores history continuity
through ordinary segments within one Task, replacing separate-record expansion.
It retains the retirement of Plan, TaskContext, StepProgress and control Tools.

The user explicitly rejected all Plan models, ToolContext, StepProgress,
AgentTool, built-in control Tools and Runner factories. Task files remain an
optional adapter. This supersedes the earlier promise to preserve those Python
APIs; historical saved Trace JSON remains readable.

```text
application prepares records -> Runner(Environment, records)
  -> Environment schedules actual Agents
  -> Agent generates -> own Review/revise -> durable commit -> private Tools
  -> Episode sealed -> independent final Verifier -> export
```

Agent directly owns instruction, model, Tools and Reviewer. Environment owns
actual Agents. Episode owns accepted messages and execution events. Tools take
one argument; ordinary closures capture application data. There are no Plan
objects, context wrappers, dependency containers or synthetic control Tools.

Delete plans.py, agent_tool.py, model_agent.py, steps.py and task_config.py.
Small JSON serialization utilities live in data.py; Seed/SeedOrigin remain input
records. These are data values, not relocated configuration or execution owners.
Providers connect directly to Responses or Chat Completions, including vLLM via
base_url. Optional server startup remains outside the core.

TaskPackage parses existing task files into frozen ordinary mappings and binds
actual dependencies outside Runner. compile/validate construct no Agents or HTTP
clients. File-declared phases expand into separate task records before execution;
applications control subsequent tasks and shared context explicitly. The prior
same-Episode step-control API is retired. run_plan and verification plan remain
historical JSON field names only; they do not reconstruct Python Plan objects.

Keep review-before-effects, durable intent, private history, local schema checks,
credential redaction, cancellation/resource cleanup, immutable generation and
append-only reverification. Invalid input keeps its identity/origin evidence.
Tests migrate to actual-object interfaces; tests requiring retired APIs are
removed explicitly, with replacement coverage recorded in ticket 05c.
