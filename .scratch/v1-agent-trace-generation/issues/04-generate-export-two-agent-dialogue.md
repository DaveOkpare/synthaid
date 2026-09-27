# 04: Generate and export a two-agent dialogue

**What to build:** Let a task author run a generic user–assistant dialogue in which the configured initiator sends the first Message, participants alternate accepted replies, and the resulting Conversation can be projected from the sole Target Agent's perspective.

**Blocked by:** 03 — Generate one deterministic single-agent Trace

**Status:** resolved

**Type:** implementation

- [x] The built-in dialogue Environment requires generic user and assistant participants and exactly one explicit Target Agent.
- [x] The configured initiator produces the opening Message and the Environment alternates participants without a declarative turn graph.
- [x] Both Agents receive the full accepted shared Conversation in canonical occurrence order.
- [x] Legitimate completion is distinguished from maximum-round or timeout truncation.
- [x] The persisted Trace contains one shared Conversation without duplicate Messages when replies are relayed.
- [x] OpenAI-style JSONL projection maps Target Agent output to assistant Messages and the other participant's shared output to user Messages.
- [x] Non-accepted status export requires an explicit option until final Verification is available.

## Answer

Added the built-in `dialogue` Environment through the existing Runner and
Interaction lifecycle. Both generic participants open Interactions, the configured
initiator goes first, and accepted references alternate without duplicate Message
Commits. Authoring requires exactly `user` and `assistant` with one explicit target.
Each participant sees the entire accepted shared history in occurrence order.

`max_rounds` bounds pairs of participant turns and produces `truncated/max_rounds`.
The optional `timeout_seconds` bounds setup and generation together, then gives
finalization a separate equal timeout; expiry produces `truncated/timeout` and
preserves durable partial history. Extension failures remain failed, including an
extension-raised `TimeoutError` that is not the Runner's deadline.

Single-step completion currently uses a typed `Message.control = "complete"`
proposal from the target, effective only after that Message is accepted and
persisted. Scripted responses accept explicit content/control tables. Script
exhaustion is a failure and plain text does not signal completion. Ticket 09 will
evolve this interim representation into reviewed framework control Tool calls;
ticket 06 must keep completion behind Message acceptance.

`export_openai` reads complete persisted snapshots, projects the explicitly marked
target to `assistant` and the other participant to `user`, retains occurrence order,
and excludes native metadata and Events. Both native and OpenAI export select
accepted statuses by default; current unverified generation requires explicit
selection. Failed partial traces can also be explicitly selected, while empty
Conversations do not become empty training records. The new `export` CLI delegates
to those exporters with format and repeatable status options.

Updated the README and added a usable `examples/scripted-dialogue` package.
Verification: 41 focused tests across `test_dialogue.py`, `test_runner.py`, and
`test_cli.py` pass; strict mypy passes for 14 source/test files; repository Ruff
lint and format checks pass. The example ran to an unverified completed Trace and
exported one four-Message OpenAI record. Full-suite/build verification and independent
review are handled by the coordinating agent. Tools, review, steps, and final
Verification remain scoped to their later tickets.
