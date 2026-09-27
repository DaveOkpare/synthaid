# 08: Support robust multi-Tool interactions

**What to build:** Let Tool-capable Agents complete ordered multi-call workflows while preserving accepted intent, validated results, failures, privacy, and partial progress as durable Trace data.

**Blocked by:** 07 — Review Tool calls before executing effects

**Status:** resolved

**Type:** implementation

- [x] A Message containing multiple Tool calls is reviewed once in the exact structure produced by the model.
- [x] Accepted calls execute sequentially in declared order and retain stable call identifiers.
- [x] Each Tool result is validated and committed separately in canonical occurrence order.
- [x] Tool execution failure is represented as a typed Tool result when the Tool contract supports it, otherwise the Trace fails with a typed reason.
- [x] A crash or later rejection can leave a valid partial Conversation ending in an accepted Tool call or result without rolling it back.
- [x] Revision exhaustion never force-accepts a Tool-call or control-action Message.
- [x] An Agent-wrapped Tool adapter can expose a subordinate Agent through the same Tool contract.
- [x] Target-oriented export includes only the Target Agent's private Tool exchanges and preserves matching call identifiers.

## Answer

An accepted multi-call Message now runs its calls sequentially in declared order.
The exact structured Message remains one review and one durable private commit;
each independently validated result commits before the next call starts. The
existing last-pending-Message rule still applies to initial, revised, and
continuation Actions, and completion of the exchange always regenerates the
Agent with its accepted history. Call identifiers must be unique within a
Message and across that Agent's accepted exchanges; different Agents retain
independent identifier namespaces.

`ToolPlan` and `task.toml` now declare `execution_errors = "fail" | "result"`,
defaulting to `fail`. Runtime declarations must match the compiled policy.
Opting into `result` turns execution exceptions into the fixed
`ToolExecutionFailure` contract, serialized as
`{"error":{"kind":"execution","exception":"ValueError"}}` in a private
result with the original call ID. Error results omit exception text and allow
remaining calls to proceed. Successful output retains its own output schema;
assignment, arguments, malformed results, unsupported actions, and persistence
failures cannot use this recovery path. Typed failures preserve durable partial
intent and completed results without rollback.

The public `AgentTool(plan, agent_factory, instruction=...)` creates a fresh
subordinate Agent for each invocation. Its Observation contains only the
explicit instruction and JSON arguments, without parent history or Tool
assignments. One assistant reply (or singleton list) must contain schema-valid
JSON. Nested Tool calls, Tool-result Messages, controls, and multiple replies
are rejected without nested execution. Typed adapter validation errors remain
failures even when execution exceptions may become results. Provenance records
the subordinate factory/class and available source digest, alongside existing
function callback provenance.

Evidence:

- Red/green Runner slices demonstrated whole-Message review, durable ordered
  results, explicit execution-error recovery, duplicate/reused ID rejection,
  isolated subordinate state/provenance, and rejection of malformed or
  effect-bearing subordinate replies.
- `uv run --locked pytest tests/test_tools.py tests/test_review.py
  tests/test_runner.py tests/test_dialogue.py -q`: **96 passed**. The 43 Tool
  cases include target-only multi-call export, actor-scoped IDs, partial progress
  after later assignment/argument/result failures or reply rejection, execution
  continuing after a committed error result, no Tool/control exhaustion fallback,
  and the retained ticket 07 Action-queue and offline-schema regressions.
- `uv run --locked mypy`: success for 22 source files. Ruff lint and format
  checks pass.
- `uv run --locked python examples/multi-tool/run.py --output
  /tmp/agentinstruct-ticket08-example`: terminated with one reviewed three-call
  Message, three matching private results (including the second call's typed
  failure), and the separately reviewed reply `ADA | Unavailable | GRACE`.

See [Tool usage](../../../README.md#review-tool-calls-before-effects) and the
[offline multi-Tool example](../../../examples/multi-tool/run.py). Runtime
factories remain the extension mechanism until ticket 16. Nested subordinate
Interaction lifecycles and provider adapters are outside this ticket. Parent
review owns the commit; final full-suite/build verification follows ticket 19.
