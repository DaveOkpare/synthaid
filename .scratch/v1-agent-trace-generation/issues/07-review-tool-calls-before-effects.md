# 07: Review Tool calls before executing effects

**What to build:** Let an Agent invoke one assigned function Tool while ensuring the exact Tool-call Message is reviewed and durably accepted before any external effect occurs.

**Blocked by:** 06 — Review and revise conversational Messages

**Status:** resolved

**Type:** implementation

- [x] A Tool declares its identifier, description, JSON input schema, optional output schema, and asynchronous call behavior.
- [x] An Agent may propose a Tool-call Message using the same OpenAI-style Message contract as other proposals.
- [x] The Tool-call Message is reviewed independently from any later conversational Message.
- [x] A rejected Tool-call Message is recorded as an Event, never committed, and never executed.
- [x] An accepted Tool-call Message is committed before arguments are validated and the Tool executes.
- [x] The validated Tool result is committed as a matching private tool-result Message and becomes visible to the invoking Agent.
- [x] The other participant cannot observe the private Tool call or result, but can receive the later accepted conversational consequence.
- [x] The default function adapter follows the same Tool protocol as a custom Tool implementation.


## Answer

Implemented Task-wide immutable `ToolPlan` declarations and unique per-Agent
assignments, with compiled JSON input and optional output schemas. Agents receive
their assigned declarations in `Observation.tools` and propose structured
`ToolCall`/`FunctionCall` Messages. The public async `Tool` contract receives an
immutable actor-aware `ToolContext`; `FunctionTool` adapts an async function and
records that callable's source identity and available digest.

The existing per-Message review loop now gates Tool effects. A rejected call
remains only Events; exhaustion never force-accepts it. An accepted call commits
privately before assignment/argument checks and execution. JSON/result-schema
validation precedes a separate private result commit with its original
`tool_call_id` and causal Message reference. The invoking Agent observes the
exchange before proposing its independently reviewed reply. Peer Observations
and non-owner target exports exclude private exchanges. Typed Tool failures keep
the accepted partial Conversation.

JSON Schema validation uses `jsonschema` with an explicit offline `referencing`
registry. Remote references never cause retrieval; unresolved references fail
argument validation after durable acceptance. Dependencies and development type
stubs were added with `uv add`, producing the corresponding lockfile update.

Evidence:

- Red/green Runner slices covered durable acceptance, assignment/argument
  failures, result schemas and base JSON validity, the function adapter and
  callable provenance, and stable call identifiers.
- Focused command `uv run pytest tests/test_tools.py tests/test_review.py
  tests/test_runner.py tests/test_dialogue.py -q`: **77 passed**. The 24 Tool cases
  include independent review budgets, rejected-call exhaustion, owner/non-owner
  privacy and export, schema preflight, and a remote-reference regression with a
  network-connection guard. Nine additional regression cases cover stale replies
  and completion controls from initial, revised, and continuation Actions, valid
  Tool-ending lists, and revisions with older pending Messages.
- `uv run mypy`: success for 21 source files; `uv run ruff check .`,
  `uv run ruff format --check .`, and `uv lock --check`: passed.
- `uv run python examples/function-tool/run.py --output
  /tmp/agentinstruct-ticket07-example`: terminated with three ordered commits,
  two independent Message reviews, and the shared reply `HELLO, ADA.`.

See [Tool usage](../../../README.md#review-tool-calls-before-effects) and the
[runnable example](../../../examples/function-tool/run.py). This ticket supports
one call per Message; ticket 08 owns multi-call robustness, richer failure
results, and Agent-wrapped Tools, while ticket 09 owns Task Step controls.
Runtime factories remain the extension mechanism pending ticket 16's explicit
import-reference loading. Parent review and full-suite/build verification follow
before the ticket commit.


### Spec review correction

Fixed the post-Tool continuation bypass identified in review. A Tool-call
Message must be the last pending Message, including Messages retained from an
original Action during revision. Otherwise generation fails explicitly before
that Tool call is reviewed, committed, or executed; previously accepted history
remains durable. This preserves ordered processing without silently dropping or
reordering a precomputed reply. Valid conversational lists and lists ending in a
Tool call retain independent per-Message review, and every successful Tool result
now unconditionally triggers Agent generation with the accepted exchange.

The six stale-reply/control cases were red before the fix and green afterward.
Focused Tools/review/Runner/dialogue checks passed 77 cases; strict mypy and Ruff
lint/format passed. No full-suite repetition or commit was made by the delegated
implementer; parent review owns the final verification and commit.
