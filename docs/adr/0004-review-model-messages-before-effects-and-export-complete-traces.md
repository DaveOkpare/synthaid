---
status: accepted
date: 2026-09-25
amends:
  - ADR-0001
  - ADR-0002
  - ADR-0003
---

# Review model messages before effects and export complete terminal traces

ADR-0002 placed generation, private tool use, review, and persistence behind `Interaction.turn()`, but treated the tool loop and outbound draft as one pending bundle. That permits a model-proposed tool call to cause an effect before the reviewer accepts it. ADR-0003 then made the whole bundle a `TurnCommit`, which delays durable recording of an accepted tool call until a later conversational draft passes.

The prototype also exposed a separate persistence requirement: a run index is useful for discovery, but it cannot be the source of exported training data. Every seed execution needs a complete terminal trace of its own, including partial failed executions.

This ADR amends the review, persistence, and export portions of ADR-0001 through ADR-0003. Their task packaging, seed compilation, environment, step, role, and final-verification decisions remain unchanged.

## Decision

### Every model-produced message crosses the review boundary

An agent's reviewer evaluates each model-produced OpenAI-style message before that message enters accepted history or causes an external effect. A message containing one or more tool calls is one review subject. Its tool calls are not executed unless the message passes review.

`Interaction.turn()` processes messages in this order:

```text
model proposes a tool-call message
  -> reviewer evaluates the tool-call message
     -> reject: record an event, return feedback, and request a revision
     -> accept: persist the tool-call message in the invoking agent's private history
        -> execute its tool calls
        -> validate and persist the corresponding tool-result messages privately
        -> call the model again with the accepted tool exchange
           -> reviewer evaluates the outbound conversational message
              -> reject: record an event, return feedback, and request a revision
              -> accept: persist and relay the message to the other participant
```

An agent that does not request a tool starts at the outbound-message review. If it requests another tool after observing a result, the same tool-call review cycle repeats. An action represented as a list of messages is processed at these message boundaries rather than reviewed as one opaque list.

Tool results are framework-produced messages. They are validated against the declared tool result protocol or schema but are not sent to the LLM reviewer. Execution errors are recorded as tool-result or failure events according to the tool protocol; they do not retroactively reject the already accepted tool-call message.

Rejected model messages remain events and never enter any model-visible history. Accepted tool-call and tool-result messages are visible only to the invoking agent. An accepted conversational message becomes part of the shared history and is therefore available to the next participant when the environment relays the turn.

### Reviewers use weighted Boolean criteria and thresholds

The active review rubric is the agent's base rubric with the current task step's rubric appended. Each criterion has a unique identifier and positive weight. A reviewer returns a complete Boolean verdict map and feedback:

```python
@dataclass(frozen=True)
class ReviewResult:
    criteria: Mapping[CriterionId, bool]
    feedback: str
```

The framework, rather than the reviewer, derives the normalized score:

```text
review_score = sum(weight of each passing criterion) / sum(all active weights)
```

The message passes when `review_score >= reviewer_threshold`. A threshold of `1.0` requires every active criterion to pass. The reviewer threshold is configured independently from the post-run verifier threshold; passing review means a message may enter the trace, while passing final verification means the completed trace is accepted for the default dataset export.

The framework validates that the reviewer returned every active criterion exactly once and no unknown criterion. Missing, duplicate, unknown, or non-Boolean verdicts fail the review operation and cannot authorize a tool effect or message commit.

Revision limits apply separately to each reviewed model message. The optional `accept_on_revision_exhaustion` policy applies only to outbound conversational messages and must be explicitly enabled. A rejected tool-call message is never force-accepted or executed; exhausting its revisions fails the action or trace.

### Accepted messages are the durable unit, not turn bundles

`MessageCommit` replaces ADR-0003's `TurnCommit` as the atomic conversation record. It appends one accepted OpenAI-style message with its `turn_id`, `step_id`, participant, visibility, review reference when applicable, and causal references.

A model message containing multiple tool calls is one `MessageCommit`. Each tool result is a later commit tied to its `tool_call_id`. The outbound conversational message is another commit. A turn record may reference the ordered commits and close when its outbound message is accepted, but a turn is not the persistence transaction.

The tool-call message is committed before execution so the accepted intent is durable before its effect occurs. Its result is committed as soon as execution returns and validates. Consequently, a crash or later review failure may leave a valid partial trace containing an accepted tool call and result without an outbound reply. The trace is marked `failed`, remains inspectable, and is excluded from default dataset exports.

This order also preserves the canonical conversation exactly as it occurred:

```text
user message
assistant tool-call message
tool-result message
assistant conversational message
user message
```

Projection, rather than storage order, enforces tool privacy. Both participants receive accepted shared conversational messages. Only the invoking participant receives its accepted tool-call and tool-result messages.

### Concrete per-seed flow

For one seed, the end-to-end flow may look like this:

```text
1. The runner reads the seed, extracts declared variables, renders instructions,
   and compiles an immutable RunPlan.

2. The user agent proposes its opening message.
   Review attempt 1 scores 0.50 against a 0.75 threshold, so the draft is
   recorded as rejected but is not added to conversation history.
   Review attempt 2 scores 1.00, so the revised message is committed and
   passed to the assistant interaction.

3. The assistant proposes a search tool-call message.
   Review attempt 1 scores 0.60 against a 0.80 threshold. The call is not
   executed and the proposed message remains only in the event stream.
   The assistant revises the arguments. Review attempt 2 scores 1.00, so
   the tool-call message is committed to the assistant's private history.

4. The framework executes the accepted call, validates the result, and commits
   a matching tool-result message to the assistant's private history. The user
   agent never sees either private tool message.

5. The assistant observes the accepted tool exchange and proposes a reply.
   Its first draft is rejected. The revised reply passes, is committed to the
   shared conversation, and is returned by `Interaction.turn()`. Only now can
   the environment give that accepted reply to the user agent.

6. The environment continues the back-and-forth loop and activates later task
   steps when required. Every step retains the accepted history above while
   adding only its current instructions and rubric criteria.

7. When the environment terminates, the runner seals the generation trace.
   The final verifier scores the complete trace against its own weighted
   criteria and threshold, assigns the terminal status, persists the complete
   trace snapshot, and adds a lightweight reference to the run index.
```

This flow ensures downstream participants consume only accepted conversational messages, while the target agent can use its own accepted tool exchanges when generating its reply.

### Every terminal trace is a complete export source

Before the runner advances to the next seed, it persists the complete terminal trace beneath that trace's directory. `traces.jsonl` is an append-only summary and locator; it is not the canonical export source.

```text
runs/<run-id>/
  source-task/                     # immutable task-package snapshot
  manifest.json                    # versions, hashes, status, timing, counts
  traces.jsonl                     # summary and path for every seed attempt
  traces/<trace-id>/
    run-plan.json                  # rendered, secret-scrubbed per-seed plan
    trace.json                     # identity, status, provenance, ordered refs
    conversation.jsonl            # accepted MessageCommit records
    events.jsonl                  # proposals, reviews, rejections, calls, failures
    verification/<attempt-id>.json
    artifacts/
```

The native trace snapshot retains the task, run, seed, and trace identities; resolved-plan provenance; accepted conversation; turn and step references; execution and review events; artifacts; verification attempts; and terminal status. It supports `accepted`, `rejected`, `unverified`, `invalid`, and `failed` traces, including durable partial traces.

Native export may include any explicitly selected terminal status. Training-oriented OpenAI JSONL export includes only `accepted` traces by default. Other statuses require an explicit inclusion option so rejected, unverified, or failed examples cannot silently enter a dataset.

The default training projection is for the sole target agent. It contains all accepted shared participant messages plus only that target's accepted private tool calls and results. Private tool exchanges belonging to simulator agents, rejected proposals, review feedback, and internal events remain available in the native trace but do not appear in the target's training messages.

OpenAI-style export preserves the message representation:

- A tool-call proposal is an assistant message with a `tool_calls` array and structured JSON arguments.
- A tool result is a tool message with the matching `tool_call_id`.
- Ordinary accepted participant messages preserve their role and content.

Reverification appends a new verification result and may change the derived export eligibility without mutating the sealed generation conversation.

## Considered Options

- **Review only the final conversational draft.** Rejected because a model-proposed tool call may already have caused an unsafe or unwanted effect before the reviewer sees the draft.
- **Review the tool call, result, and conversational draft as one bundle.** Rejected because the tool must execute before its result exists, so the bundle cannot be reviewed before the effect. It also hides the distinct decisions to authorize an effect and accept a reply.
- **Force-accept a tool call after its revision limit.** Rejected because a liveness fallback must not authorize a tool effect that failed its rubric.
- **Commit an entire turn atomically after the outbound draft passes.** Rejected because accepted intent and completed effects would be lost if the process fails before the later draft is accepted.
- **Keep only the run index and reconstruct traces for export.** Rejected because an index does not contain the conversation, events, provenance, or verification detail needed for reproducible datasets.
- **Export every terminal status by default.** Rejected because negative and unverified traces could silently contaminate training data.

## Consequences

- Review latency increases because tool-call messages and conversational messages are evaluated independently.
- No framework-managed tool effect occurs without an accepted, durable model message authorizing it.
- Partial failed traces are first-class records and may legitimately end after a tool call or result.
- Reviewer and verifier thresholds share weighted Boolean scoring semantics but remain separate policies at different lifecycle boundaries.
- Conversation persistence becomes incremental and crash-auditable rather than all-or-nothing at the turn level.
- Complete per-seed trace snapshots require more storage, but dataset export no longer depends on transient in-memory state or incomplete indexes.
- Default exports contain accepted target-facing training examples while native traces retain the evidence needed for inspection, debugging, and alternative downstream projections.

## References

- [ADR-0001](./0001-data-generation-first-agent-trace-architecture.md)
- [ADR-0002](./0002-use-run-based-dialogue-environments.md)
- [ADR-0003](./0003-compile-one-run-plan-per-seed.md)
- [Interactive state prototype](../../prototypes/trace-generation-state-prototype.html)
