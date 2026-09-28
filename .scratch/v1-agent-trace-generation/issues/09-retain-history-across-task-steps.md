# 09: Retain history across Task Steps

**What to build:** Let a multi-step Task reveal fresh role-specific instructions and Criteria at ordered checkpoints while continuing one accepted Conversation and each Agent's private Tool history.

**Blocked by:** 07 — Review Tool calls before executing effects

**Status:** resolved

**Type:** implementation

- [x] A Task may declare ordered, uniquely named Task Steps or omit them entirely for a single-step Task.
- [x] Each Agent keeps its base instruction while only the current Task Step's instruction addition is active.
- [x] Current-step Criteria append to the Agent's base Rubric and composed Criterion identifiers remain unique.
- [x] Previous Task Step instruction and Rubric additions expire when the next step activates.
- [x] Accepted shared Messages and invoking-Agent-private Tool exchanges remain available across step changes.
- [x] Step advancement and Task completion use controlled, reviewable actions rather than out-of-band history mutation.
- [x] The Trace records Task Step activation and associates Messages, Events, and reviews with the active step.

## Answer

`[task] steps = ["collect", "conclude"]` declares the ordered phases. Package
loading validates unique portable names, exact declared directories, participation
by every Agent, safe instruction/rubric paths, and composed Criterion uniqueness.
All step instructions render into immutable Step Plans before generation starts.
Step Rubrics contain Criteria only: an explicit threshold is rejected, while the
base Agent Rubric's threshold remains authoritative. Deterministic Reviewer checks
cover the union of declared Criteria and score only the currently active Rubric.

A trace-bound step state supplies base plus current-step instructions and Criteria
to every Interaction without replacing the canonical Conversation. Shared accepted
Messages and each participant's private Tool exchanges remain in their existing
order and privacy projection. Observation, ReviewRequest, ToolContext, Message
Commits, and Events retain step references. Activation records identify the new
step; an advance call and its private result retain the old step that authorized
the transition.

Reserved `advance_step` and `complete_task` Tools pass the same review, revision,
durable intent, argument validation, and private-result boundary as other Tools.
Controls must be isolated calls and last in the pending Action queue, including
revisions and continuations. Only the Target may invoke them, advancement must
name the immediately following step, and only the final step may complete. The
Target observes only the currently available control declaration, with the next
step ID in the advance schema. Completion still generates a final separately
reviewed reply, with no Tools advertised or executable afterward. Single-step
`Message.control="complete"` remains compatible; stepped Tasks explicitly require
the Tool-call form.

Immutable `TaskContext.steps` exposes ordered IDs. Its `advance_step()` and
`complete_task()` helpers construct Messages that an Environment submits through
the Target's `Interaction.control()`, including the same exhaustion guard.
TaskContext exposes no recorder or arbitrary history mutation. A custom
Environment cannot mark a stepped Task terminated without accepted completion;
that outcome becomes `truncated/incomplete_steps`. Built-in single-agent stepped
execution uses `max_turns`, while dialogue retains the global `max_rounds` bound.

Evidence:

- Red/green Runner slices established instruction/history retention, composed
  review policy, structural control isolation, static preflight, controlled
  Environment completion, and phase-specific Tool availability.
- `uv run --locked pytest tests/test_steps.py tests/test_tools.py
  tests/test_review.py tests/test_runner.py tests/test_dialogue.py -q`:
  **135 passed**, including **39 Task Step cases**. These cover both Agents'
  retained private Tool histories and target export, rejected/revised controls,
  exhaustion fallback exclusion, Environment controls, stale Action tails,
  invalid progress/ownership, later-template failure before generation, safe
  links, layout/reference collisions, and invalid step Rubrics.
- `uv run --locked mypy`: success for 24 source files. `uv run --locked ruff
  check .`, `uv run --locked ruff format --check .`, and `git diff --check`: passed.
- `uv run --locked agentinstruct validate examples/stepped-dialogue --json`:
  valid rendered two-step Plan for both participants.
- `uv run --locked python examples/stepped-dialogue/run.py --output
  /tmp/agentinstruct-ticket09-example`: terminated with 12 ordered commits,
  reviewed private lookup/advancement/completion, and the final reply
  `conclude: Hello, Ada.` using the earlier private lookup.

See [Task Step usage](../../../README.md#retain-history-across-task-steps) and the
[offline example](../../../examples/stepped-dialogue/run.py). Runtime factories
remain the extension mechanism until ticket 16; Seed collections and Providers
remain in their own tickets. The example omits final Verification and therefore
produces an unverified Trace. Parent review owns this ticket's commit; the final
full-suite/build verification follows ticket 19.

### Standards review follow-up

Extracted shared source-labelled template loading/preflight and rendering helpers
for base instructions, Reviewer instructions, and Task Step additions. Safe path
resolution, strict sandbox behavior, exception classifications, source snapshots,
and compilation before generation remain unchanged. The existing later-step
failure regression now also requires its precise instruction path in both static
and rendering diagnostics.

`uv run --locked pytest tests/test_steps.py tests/test_review.py
tests/test_runner.py tests/test_cli.py -q`: **89 passed**. Strict mypy, Ruff lint,
Ruff format, and `git diff --check` passed. No commit was made by the delegated
implementer; parent rereview and amendment follow.
