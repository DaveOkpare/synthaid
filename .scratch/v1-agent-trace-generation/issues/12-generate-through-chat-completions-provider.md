# 12: Generate through a Chat Completions Provider

**What to build:** Let an Agent generate a complete Trace through the framework-owned semantic Provider boundary using an OpenAI-compatible Chat Completions surface without leaking vendor SDK models into the domain.

**Blocked by:** 03 — Generate one deterministic single-agent Trace

**Status:** ready-for-agent

**Type:** implementation

- [ ] The asynchronous Provider protocol exposes capabilities, one semantic generation operation, and asynchronous cleanup.
- [ ] The normalized request carries ordered Messages, model identity, function Tools, Tool choice, response-format requirements, inference controls, and trace-safe metadata.
- [ ] The normalized response carries one proposed assistant Message, finish state, usage, request identity, latency, and safe metadata.
- [ ] A deterministic fake transport proves an OpenAI-compatible Chat Completions adapter can drive a full single-agent Trace.
- [ ] Provider credentials are resolved at runtime and never enter Run Plans, Events, errors, or Trace provenance.
- [ ] Authentication, authorization, rate limit, timeout, network, invalid request, unsupported feature, unavailable model, server, malformed response, and unknown errors remain distinguishable.
- [ ] No automatic Provider retry occurs and the Runner closes Provider resources.
- [ ] Capabilities are checked before inference when the required feature is statically knowable.
