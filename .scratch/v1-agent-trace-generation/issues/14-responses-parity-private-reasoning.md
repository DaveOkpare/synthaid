# 14: Add Responses API parity and private reasoning

**What to build:** Let the OpenAI Provider use Responses by default while preserving the same Agent, Tool, Reviewer, Verifier, and Trace semantics as Chat Completions.

**Blocked by:** 07 — Review Tool calls before executing effects; 13 — Use Pydantic structured outputs for quality gates

**Status:** resolved

**Type:** implementation

- [x] Each Provider Plan selects Responses or Chat Completions explicitly and the selected surface is immutable and recorded in provenance.
- [x] The OpenAI Provider defaults to Responses and never silently falls back to Chat Completions.
- [x] Complete accepted history is translated to self-contained Responses input with provider storage disabled by default.
- [x] Authoritative Conversation state never depends on a provider response identifier.
- [x] Responses text, function calls, function-call outputs, refusals, incomplete states, usage, and native identifiers normalize to framework models.
- [x] Equivalent requests through both surfaces produce semantically equivalent Messages and parsed values in contract tests.
- [x] Returned reasoning remains participant-private Event data, is never relayed or inserted into Conversation, and is excluded from default training export.
- [x] A policy may suppress full reasoning text while retaining presence and usage metadata.
- [x] Provider-hosted Tools remain unsupported because they can bypass review-before-effect.

## Answer

Implemented Responses as the default OpenAI runtime surface with explicit API
selection and no fallback. Both adapters share lazy HTTP transport, credential
scrubbing, classified failures, cleanup and mandatory structured-output validation.
Responses translates complete accepted history to stateless input, paired function
calls/results, all portable Tool choices and `text.format`, retaining native item
identities and usage. Refusal and incomplete states take precedence over partial
Tool arguments on both surfaces; unsupported hosted Tools never become proposals.

Added typed `ReasoningControls` to inherited Model Plans and requests, plus the
Provider's snapshotted `retain_reasoning` policy. Returned `ReasoningItem` values
stay private model-call evidence, including Reviewer calls and append-only Verifier
attempts. Suppression preserves presence and usage while excluding full text and
opaque encrypted payloads from disk. Accepted Tool continuations retain only the
same actor's newly accepted exact proposal, preserve reasoning/function ordering,
and use ephemeral private data when retention is disabled. Rejected reasoning is
never replayed. Conversation, peer observations and OpenAI training exports exclude
reasoning; original generation files remain unchanged by reverification.

Validation: 186 focused tests passed across Responses, existing Providers,
structured output, model quality, import safety and Task Steps. The affected
Runner/CLI/package-safety/model-quality group passed 82 tests. Strict mypy and Ruff
pass. CLI and default-Provider failure fixtures now use deliberately missing
credential references, so enabling Responses cannot trigger live inference.
All transport tests are deterministic; no real inference or full suite/build was
run. Generic compatible/vLLM profile enablement remains ticket 15.

See [usage and retention policy](../../../README.md#generate-through-responses-and-retain-private-reasoning),
[Responses translator](../../../src/agentinstruct/responses.py), and
[public contract tests](../../../tests/test_responses.py).

Review follow-up: Responses `status = "failed"` now classifies documented safe
error codes through the same normalizer as HTTP failures. Rate limits, invalid
prompts, timeouts, unavailable models and unsupported parameters retain their
stable categories, safe code and request/response identity. Unknown codes and raw
error messages are never persisted. Seven added public transport regressions
cover cross-surface categories, single-attempt cleanup and credential omission;
150 Provider/structured/quality tests, strict mypy and Ruff pass after the fix.
