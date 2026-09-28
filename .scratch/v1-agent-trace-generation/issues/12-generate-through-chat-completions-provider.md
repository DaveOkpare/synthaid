# 12: Generate through a Chat Completions Provider

**What to build:** Let an Agent generate a complete Trace through the framework-owned semantic Provider boundary using an OpenAI-compatible Chat Completions surface without leaking vendor SDK models into the domain.

**Blocked by:** 03 — Generate one deterministic single-agent Trace

**Status:** resolved

**Type:** implementation

- [x] The asynchronous Provider protocol exposes capabilities, one semantic generation operation, and asynchronous cleanup.
- [x] The normalized request carries ordered Messages, model identity, function Tools, Tool choice, response-format requirements, inference controls, and trace-safe metadata.
- [x] The normalized response carries one proposed assistant Message, finish state, usage, request identity, latency, and safe metadata.
- [x] A deterministic fake transport proves an OpenAI-compatible Chat Completions adapter can drive a full single-agent Trace.
- [x] Provider credentials are resolved at runtime and never enter Run Plans, Events, errors, or Trace provenance.
- [x] Authentication, authorization, rate limit, timeout, network, invalid request, unsupported feature, unavailable model, server, malformed response, and unknown errors remain distinguishable.
- [x] No automatic Provider retry occurs and the Runner closes Provider resources.
- [x] Capabilities are checked before inference when the required feature is statically knowable.

## Answer

Implemented the framework-owned asynchronous Provider boundary and an explicit
Chat Completions adapter using lazy HTTPX clients. Immutable semantic requests
carry ordered Messages, Tools/choice, response-format requirements, controls and
safe identity metadata; responses normalize one assistant proposal, finish state,
strict usage, request identity, latency and allowlisted metadata. The adapter makes
one stateless request with `store = false`, has no retries or API fallback, resolves
credentials only at inference, and scrubs echoed credentials (including decoded
Tool arguments) before they can reach recorded data.

Runner-managed model Agents preserve actor-relative roles, private Tool history,
review feedback and current Step controls. Provider proposals continue through the
existing review/commit/Tool boundaries. All used surfaces are capability-checked
before any inference; scripted/custom Agents avoid unused Providers. Cleanup runs
on success, classified failures and timeout. Provider errors distinguish every
requested category, including unknown endpoints versus unavailable models; refused
or incomplete output cannot execute effects.

Validation: 38 deterministic Provider tests at the public Runner and semantic
Provider/HTTP transport seams; 156 focused Provider, import-safety, Runner, Tool,
review and Step tests pass. Mypy, Ruff lint/format checks and offline validation of
`examples/chat-completions` pass. HTTPX was added and locked with `uv add`.
No live service was called. Full suite/build remain the final ticket-19 gate.

See [Provider usage](../../../README.md#generate-through-a-chat-completions-provider)
and [the model example](../../../examples/chat-completions/task.toml). Structured
result validation/quality gates remain ticket 13, Responses/private reasoning 14,
and vLLM runtime profiles/conformance 15. The OpenAI Responses default remains
compiled but explicitly unsupported at runtime until its adapter exists.
