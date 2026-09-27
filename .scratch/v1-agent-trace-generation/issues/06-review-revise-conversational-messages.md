# 06: Review and revise conversational Messages

**What to build:** Let a task author enable an Agent Reviewer that evaluates each conversational Message proposal against a weighted Rubric and prevents rejected drafts from entering accepted history or reaching another participant.

**Blocked by:** 04 — Generate and export a two-agent dialogue

**Status:** resolved

**Type:** implementation

- [x] Review can be enabled independently for each Agent and uses stable Reviewer instructions plus the Agent's active Rubric.
- [x] The Reviewer returns one Boolean per Criterion plus feedback, while the framework validates the mapping and computes the normalized score.
- [x] A below-threshold proposal is recorded as an Event, excluded from the Conversation, and revised with Reviewer feedback.
- [x] Maximum revisions count additional proposals after the initial rejection and apply the full review boundary to every revision.
- [x] Only an accepted conversational Message is committed and relayed to the other Agent.
- [x] Revision exhaustion truncates by default; explicit fallback may accept only a conversational Message and marks it review-exhausted.
- [x] Malformed Reviewer output cannot commit a Message.

## Answer

Implemented independent per-Agent Review configuration, stable seed-rendered
`reviewer.md` instructions, weighted `rubric.toml` Criteria, immutable Reviewer
Plans, and fresh Reviewer factory instances for every Agent in each Trace.
`Reviewer.review(ReviewRequest)` returns Boolean evidence and feedback; the
framework reuses `quality.py` to validate verdicts and derive the inclusive score.

Interaction reviews each Message before commit or completion. Rejected Messages
remain exact Events, while private revision feedback travels separately in
`Observation.review_feedback`. Review requests, results, rejections, revisions,
errors, and accepted commits retain stable review, Message, Agent, and turn
references. The accepted Conversation, peer projection, and training export omit
rejected drafts and private feedback.

`max_revisions` counts additional proposals, defaults to one, and permits zero.
Both initial and revised Actions may be ordered lists. A revised list's first
Message replaces the rejected proposal using its remaining budget; additional
Messages are independent review subjects processed before the earlier Action's
remaining Messages. Default exhaustion yields `truncated/review_exhausted`.
Explicit conversational fallback marks the commit `review_exhausted`; it never
force-accepts `control="complete"`. Malformed verdicts and Reviewer exceptions
produce linked failure evidence and cannot commit or use the fallback.

The built-in deterministic Reviewer provides a declared `nonempty_content` check
for offline Tasks. See [usage](../../../README.md#review-and-revise-messages) and
the [reviewed dialogue](../../../examples/reviewed-dialogue/task.toml). Tools,
step-specific Rubric additions, and provider-backed judges remain in their
subsequent tickets.

Validation: 28 new review scenarios pass through the agreed public Runner,
persisted Trace, and Dataset seams. The focused Review, Runner, dialogue, and
Verification regression suite passes all 86 tests. Mypy, Ruff lint and format,
and `git diff --check` pass. The offline CLI example produces one accepted Trace.
The parent performs the final full-suite/build and independent review before
committing this ticket.

Standards-review follow-up: Reviewer and Verifier Rubrics now share one loader
with package-relative path safety and precise, input-scrubbed TOML/field errors.
Their execution lifecycles remain separate. The existing public validation test
now checks the offending Reviewer Rubric field; all 65 focused Review,
Verification, and Runner tests, mypy, Ruff lint/format, and diff checks pass.
