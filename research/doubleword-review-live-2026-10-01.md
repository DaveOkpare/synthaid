# Doubleword per-turn Review, Revision, and Tool effects

Date: 2026-10-01. Model: `Qwen/Qwen3.6-35B-A3B-FP8`, realtime Chat Completions.

**The live review/revision mechanism worked, including correction of a missing
Tool call.** Both natural scenarios passed final Verification in the follow-up.
Controlled tests also demonstrated that a rejected Tool proposal has no effect,
an accepted Tool runs once, and revising the subsequent reply reuses its result.
The initial natural run exposed model-Reviewer false rejections, so the evidence
does not establish that arbitrary model rubric judgments are reliable.

## Experiment

The [runnable experiment](../examples/doubleword-medagent/review_smoke.py) extends
the [earlier smoke](doubleword-live-smoke-2026-09-30.md). It uses the same two
non-personal medagent scenario projections, participant prompts, model settings,
two-round Environment, and final Verifier. It adds a per-Message assistant
Reviewer with one structural criterion, threshold 1.0, two revisions, and no
acceptance fallback. Before a Tool result exists, a proposal must call
`read_scenario({})`; after that result, it must provide text without another call.
Review applies independently to a Tool-call Message and to an outbound reply.

The original Task Package remains unchanged. Generated variants and full Run
snapshots record each experiment's instructions. Calls use temperature zero,
384 completion tokens, `reasoning_effort = "none"`, and no automatic retries.
Each invocation shares a 48-request cap, 32,000-byte request-body cap, 45-second
HTTP timeouts, and a 240-second generation deadline per Seed.

## Natural model generation and revision

The initial run used feedback-writing guidance that the model misinterpreted as
an additional acceptance requirement. For nutrition, it approved the Tool call,
then falsely rejected three nonempty text replies that satisfied the structural
rubric. Two live model revisions occurred; the revision cap then truncated the
conversation and final Verification rejected it. The last Reviewer's Boolean
was false even though its feedback argued that the verdict should be true.
The framework followed the Boolean verdict, as specified; it did not infer an
override from the prose. This is a model-judgment failure, not a bypass of gating.

The other initial Seed received HTTP 400 on the user simulator's first model
request, before per-turn review. Its Trace is failed. The original error response
body was not retained, so its root cause is unknown. It did not recur in the
follow-up; no API fix or retry guarantee is claimed.

The follow-up changed only the natural Reviewer instruction: an explicit decision
table replaced the ambiguous guidance, and a passing verdict uses feedback
`Pass`. Participant prompts, rubric, threshold, model, Tools, and final Verifier
were unchanged. Request-body/status journaling was added for diagnosis; it does
not modify requests. All 20 follow-up requests returned HTTP 200.

| Scenario | Observed review and revision | Tool executions | Final status |
|---|---|---:|---|
| Conflicting advice | Initial prose omitted the Tool; rejected. Live model received feedback, proposed `read_scenario({})`, and passed. Both subsequent replies passed. | 1 | Accepted |
| Nutrition | Tool proposal and both replies passed without revision. | 1 | Accepted |

The first case directly demonstrates a real model revision repairing missing
Tool use. Its revision request contained the private feedback and accepted user
message, with no rejected draft in history. Both accepted records were exported.
The result is a two-scenario smoke, not a statistical quality improvement estimate.

## Controlled Tool-effect probes

These use **scripted participant proposals and revisions with a live model
Reviewer**. They isolate framework ordering from the model's chance of naturally
producing a bad Tool call. They are not evidence of model-generated correction;
that evidence comes from the natural conflicting-advice case above.

1. **Tool rejection, then reply rejection:** the first valid-shaped call carries
   `BLOCK_THIS_CALL`. The Reviewer rejects it. A revised call passes and executes
   once. The next reply contains `REJECT_THIS_REPLY` and is rejected. Its revision
   uses the existing Tool result and passes, without running the Tool again.
   The verdict sequence is false, true, false, true, true; the last verdict covers
   the second conversational reply. Each rejected Message used its own one-revision
   budget.
2. **Tool exhaustion:** two blocked Tool proposals are rejected. The one-revision
   limit is exhausted; zero Tool executions or effects occur. Even with
   `accept_on_revision_exhaustion = true`, a rejected Tool call is not accepted.

The Tool's only added effect is appending a local audit entry. It checks that the
accepted call is in `conversation.jsonl` before execution. Event ordering also
shows an accepted review and message commit before every `tool_started` event.
Rejected proposals never appear in accepted Conversation history. The other
participant sees accepted replies, but no private Tool messages or review feedback.
Tool-derived information may of course be included in an accepted shared reply.

The controlled Traces are intentionally unverified because they have no final
Verifier. They remain outside default OpenAI exports. Exhaustion is a truncated
generation with reason `review_exhausted`, not a successful conversation.

## Independent checks and limitations

An offline comparison of every Reviewer verdict to the structural criterion
found three false rejections in the initial natural run, zero mismatches in the
seven controlled judgments, and zero mismatches in the seven follow-up judgments.
Saved request payloads confirm that the user simulator never received private
Tool messages or review feedback. The rejected draft and private feedback were
absent from accepted training exports. All ten recorded ordering, isolation,
effect-count, exhaustion, and repair assertions passed.

These checks cover structural Tool discipline. They do not score the generated
medical advice, sentence limits, or invented scenario details. The accepted
conflicting-advice output includes a questionable suggestion about choosing
medication instructions; it must not be treated as clinically validated. The
framework enforces the verdict it receives, while a model Reviewer can still
misjudge a rubric. Mechanically checkable requirements would benefit from
deterministic checks alongside semantic review; this experiment did not change
the framework or introduce that policy.

87 existing Review, Tool, and model-quality tests passed. Lint, formatting,
strict typing, and offline Task Package validation also passed.

## Usage and retained evidence

There were 39 HTTP inference attempts: 19 in the initial experiment and 20 in the
follow-up. 38 returned model usage; the first HTTP 400 had no usage. Observed totals
are 25,420 input tokens and 2,909 output tokens. At the realtime uncached rates
verified in the [30 September research](doubleword-inference.md), the estimate is
**$0.0064678**, excluding any unknown charge for the failed request. Account billing
was not queried.

Local evidence is git-ignored and preserved in:

- `runs/doubleword-review-2026-10-01/report.json`: initial natural run and both controls.
- `runs/doubleword-review-2026-10-01-clarified/report.json`: successful natural follow-up.
- `runs/doubleword-review-2026-10-01-clarified/analysis.json`: independent checks and usage.
- `runs/doubleword-review-2026-10-01-clarified/requests.jsonl`: header-free request journal.
- `runs/doubleword-review-2026-10-01-clarified/natural/openai.jsonl`: two accepted records.

Follow-up Trace IDs are `3ef9c3bdb3d54fc4a36a261a98d618d1` and
`5b3533e945c848f2af13f1582a3d1fc7`. The source data remained unchanged, and a scan of
102 evidence files found no resolved API credential. Only the previously selected
non-personal scenario projections were submitted; no full medagent records were used.
