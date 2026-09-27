---
status: accepted
date: 2026-09-27
amends:
  - ADR-0001
  - ADR-0003
---

# Use an OpenAI-shaped Provider protocol with vLLM conformance

> Amended by [ADR-0006](./0006-support-responses-and-chat-completions-with-pydantic-structured-outputs.md), which promotes the OpenAI Responses API to a supported Provider surface, makes it the default for the OpenAI adapter, and adds `Pydantic.BaseModel` structured-output schemas.

The existing architecture assigns models and provider defaults in `task.toml`, but it does not define the boundary between an Agent and the service that performs inference. Allowing Agents to call a vendor SDK directly would couple observation construction, tool handling, review, tracing, and error behavior to that SDK. Treating every OpenAI-compatible endpoint as identical would also hide material differences in structured outputs, reasoning extraction, tool parsing, and server configuration.

We need one small extension point for OpenAI, vLLM, and future inference services. OpenAI Chat Completions is the initial wire-shape baseline because the framework already uses OpenAI-style Messages and vLLM exposes the corresponding OpenAI-compatible endpoint. vLLM is a required, tested Provider rather than an assumed consequence of accepting a custom base URL.

This ADR amends ADR-0001's built-in Agent decision and ADR-0003's `ModelPlan`/component-preflight decision. It does not change ADR-0004's acceptance boundary: a Provider returns model proposals, while `Interaction.turn()` reviews tool-call and conversational Messages before they cause effects or enter accepted history.

## Decision

### Agents depend on an owned Provider protocol

`Provider` is the asynchronous inference boundary. The framework owns every request and response model; vendor SDK types do not cross it.

```python
class Provider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def complete(self, request: ProviderRequest) -> ProviderResponse: ...

    async def aclose(self) -> None: ...
```

`Agent` remains responsible for turning an Observation into a model request and interpreting the returned proposal. `Provider` is responsible only for translating the normalized request to one inference API, translating the response back, reporting usage and metadata, and classifying transport or provider failures. It does not own Conversation history, Tool execution, review, revision, participant scheduling, or persistence decisions.

A Provider client may be shared safely across Traces when its transport is stateless, but every request is self-contained. Closing Providers is a Runner lifecycle responsibility.

### The request and response models are OpenAI-shaped but framework-owned

`ProviderRequest` contains:

- the provider model identifier;
- ordered OpenAI-style Messages;
- function Tool definitions using JSON Schema;
- `tool_choice` as `none`, `auto`, `required`, or one named function;
- an optional portable response format of text, JSON object, or JSON Schema;
- optional reasoning controls;
- normalized sampling and token limits;
- trace-safe request metadata; and
- one typed provider-specific options object when a portable field cannot express a capability.

`ProviderResponse` contains:

- exactly one proposed assistant Message, including ordered Tool calls when present;
- optional reasoning output stored separately from Message content;
- finish reason;
- provider and model identifiers;
- normalized prompt, completion, reasoning, and total usage when supplied;
- provider request ID and latency metadata; and
- secret-scrubbed provider metadata needed for the native Trace.

Provider-specific request fields do not become arbitrary top-level dictionaries in the core API. Each built-in adapter defines a typed options model. Unknown fields are rejected rather than silently ignored.

The initial baseline is non-streaming Chat Completions. A future streaming method or Responses API adapter may implement the same semantic request and response models without changing Agent, Interaction, Reviewer, or Verifier contracts.

### Provider capabilities are explicit and preflighted

`ProviderCapabilities` declares at least:

- supported Tool-choice modes;
- support for parallel Tool calls;
- portable structured-output modes;
- provider-native structured-output modes;
- reasoning extraction and configurable reasoning controls;
- multimodal Message support when later added; and
- whether the adapter can perform an endpoint/model preflight.

The Compiler derives a Trace's required capabilities from its Agent, Reviewer, Verifier, Tools, and structured-output settings. Component preflight rejects an incompatible Run Plan before its first generation call whenever the capability is knowable.

An OpenAI-compatible endpoint does not provide a universal discovery response for model-specific parsers or server launch flags. The vLLM Provider therefore combines adapter capabilities with explicit Task configuration and an optional endpoint/model probe. Configuration claims are preserved in Run Plan provenance. A server that contradicts those claims produces a typed `UnsupportedFeature` or `MalformedProviderResponse` failure rather than silent degradation.

### OpenAI Chat Completions is the default compatibility profile

The built-in provider identifiers are:

- `openai`: the default OpenAI Chat Completions adapter;
- `openai-compatible`: the portable Chat Completions profile with a configurable base URL; and
- `vllm`: the OpenAI-compatible profile plus typed vLLM structured-output and reasoning behavior.

All three use the framework's Message, Tool, request, and response models. OpenAI credentials are read from an environment variable or injected secret source. A configured base URL, API-key environment-variable name, timeouts, and non-secret headers may appear in a Provider Plan; resolved secret values never enter a Run Plan or Trace.

Models reference a Provider by Task-wide identifier. Task-level model and Provider defaults may be overridden per Agent and Reviewer as already decided, but the resolved Provider and model are immutable within one Run Plan.

The compatibility profile follows the OpenAI Chat Completions meanings for `messages`, `tools`, `tool_choice`, `response_format`, Tool-call IDs, usage, and finish reasons. Portable structured Reviewer and Verifier results use `response_format.type = "json_schema"` when supported and are always validated again by the framework after decoding.

OpenAI recommends its Responses API for new OpenAI-specific applications, but Chat Completions is the V1 portability baseline because it matches the framework's accepted Message model and the vLLM surface required here. A Responses adapter can be added behind the same Provider protocol later.

### vLLM is a first-class adapter, not only a custom base URL

`vllm` sends requests to a separately managed OpenAI-compatible vLLM server. The framework does not import or embed the vLLM inference engine in its core environment, and using vLLM does not change the selected `local` Runtime. This avoids imposing vLLM's hardware and Python constraints on every library installation.

The adapter supports the following V1 features:

1. **Portable JSON structured output.** JSON object and JSON Schema use OpenAI-compatible `response_format` fields.
2. **vLLM-native structured output.** Typed vLLM options cover current `structured_outputs` modes for JSON, choice, regex, grammar, whitespace pattern, and structural tags. Removed `guided_*` request fields are not exposed.
3. **Reasoning output.** The adapter reads the current vLLM `reasoning` field and normalizes it to `ProviderResponse.reasoning`. It may decode the legacy `reasoning_content` alias for an explicitly supported older server, but that name never enters the core model.
4. **Reasoning controls.** Typed options support `reasoning_effort`, `thinking_token_budget`, `include_reasoning`, and model-specific `chat_template_kwargs` where the configured server supports them.
5. **Tool calling.** Tools and JSON Schema arguments use the OpenAI function-Tool shape. `none`, `auto`, `required`, and named function choice are supported when the server profile declares them. Multiple returned calls remain ordered in one assistant Message.
6. **Combined features.** Reasoning plus structured output and reasoning plus Tool calling are supported only when the selected model, vLLM version, reasoning parser, Tool parser, chat template, and structured-output configuration pass the conformance suite.

Automatic vLLM Tool choice generally requires the server to be launched with `--enable-auto-tool-choice` and an appropriate `--tool-call-parser`; many models also require the correct chat template. Reasoning extraction requires a matching `--reasoning-parser`. The adapter does not guess these model-dependent values. A vLLM server profile records the expected parser names and feature flags as provenance and capabilities, without treating those server flags as framework secrets.

The initial real-server conformance profile uses a small model from a currently documented family that supports reasoning, JSON structured output, and Tool calling, with `Qwen/Qwen3-1.7B` as the reference profile. The profile remains test configuration rather than a hard-coded library default because vLLM's model/parser compatibility matrix evolves.

### Reasoning remains private model-call data

Reasoning is not ordinary participant content. When a Provider returns it:

- it is attached to the model-call Event and participant-private Trace data;
- it is never inserted into the accepted Conversation;
- it is never relayed to another Agent;
- it does not become the text of a Tool-call Message;
- it is excluded from the default OpenAI training export; and
- the native Trace records whether reasoning was requested, returned, omitted, or suppressed.

V1 retains returned reasoning in the native Trace by default because trace generation and auditability are first-class goals. A Task or Run policy may disable full reasoning retention while retaining usage and presence metadata. Provider responses that do not expose reasoning remain valid; the framework never attempts to reconstruct hidden reasoning from content.

For vLLM, reasoning and final content must remain separate. Tool parsing operates on the final content rather than reasoning output, matching vLLM's documented behavior. An adapter must reject or explicitly classify a malformed response that embeds an apparent Tool call only in reasoning when the final Message has no valid Tool call.

### Tool safety remains above the Provider

A Provider returning a Tool call does not authorize execution. It returns an assistant Message proposal to the Interaction. ADR-0004 still requires that exact Tool-call Message to pass its active weighted Rubric threshold and be durably committed before the Tool runs.

The adapter validates response shape, Tool-call identifiers, function names, and JSON argument syntax. The Interaction validates that each Tool is assigned to the Agent and validates arguments against the framework Tool schema. No Provider executes a function or trusts generated arguments merely because constrained decoding produced them.

### Failures are typed and are not automatically retried

Provider failures are classified at the boundary as authentication, authorization, rate limit, timeout, network, invalid request, unsupported feature, unavailable model, provider server error, malformed response, or unknown provider error. The native Event retains safe request/response metadata and the original cause without credentials.

V1 performs no automatic Provider retries. A caller or future retry policy can distinguish transient categories, but hidden retries would obscure model-call count, cost, timing, and partial effects.

### Provider conformance tests are reusable

Every Provider adapter runs the same contract suite against a deterministic fake transport. The suite verifies:

- ordinary assistant text;
- ordered input Messages and output Message normalization;
- JSON Schema structured output and client-side validation;
- Tool definitions and `none`, `auto`, `required`, and named Tool choice;
- single and multiple Tool calls with stable IDs and valid JSON arguments;
- reasoning separation and retention policy;
- usage, finish-reason, request-ID, and metadata normalization;
- timeout, HTTP, malformed-payload, and unsupported-capability errors;
- secret scrubbing; and
- clean asynchronous shutdown.

The vLLM support claim additionally requires an integration suite against a real, pinned vLLM server rather than only mocked OpenAI-shaped responses. The suite verifies:

- plain Chat Completions;
- JSON Schema structured output;
- at least one vLLM-native structured-output mode;
- extracted `reasoning` separate from final content;
- automatic Tool choice and schema-valid arguments;
- Tool-result continuation;
- reasoning with Tool calling; and
- reasoning with structured output where the tested model profile supports the combination.

The real-server suite records the vLLM version, model revision, server flags, parser names, chat template, hardware class, and request profile. It may run on an opt-in GPU job rather than ordinary CPU pull-request CI, but it is required before releasing a version that claims compatibility with that vLLM version. Core CI still runs the deterministic vLLM adapter contract tests on every change.

The vLLM server is external to the package's Python environment. Its version is pinned by the conformance harness or deployment image, not added as a mandatory `agentinstruct` runtime dependency.

## Considered Options

- **Let each Agent call its provider SDK directly.** Rejected because provider concerns would spread into Agent implementations and make review, tracing, errors, structured output, and testing inconsistent.
- **Use vendor SDK request and response classes as the public interface.** Rejected because SDK upgrades would become framework API changes and vLLM-specific fields would leak unpredictably through model extras.
- **Treat vLLM as a generic OpenAI-compatible base URL.** Rejected because reasoning extraction, native structured-output modes, parser flags, and combined-feature limitations require explicit normalization and conformance evidence.
- **Depend on the vLLM Python package and call its engine directly.** Rejected for V1 because it would couple the core library to heavy hardware-specific dependencies and bypass the required OpenAI-compatible service boundary.
- **Adopt the OpenAI Responses API as the only V1 baseline.** Deferred because Chat Completions aligns with the established Message model and the widest vLLM compatibility surface. The Provider protocol permits a later Responses adapter.
- **Expose one untyped `extra_body` mapping for every provider.** Rejected because typos and removed fields would silently weaken generation guarantees. Typed provider options keep extensions explicit and testable.
- **Place reasoning in the assistant Message content.** Rejected because it would leak private model work into participant-visible Conversation history and change Tool parsing and training exports.
- **Mock vLLM without running it.** Rejected as the sole evidence because parser, chat-template, and combined-feature behavior exists in the real server and model, not in the OpenAI wire shape alone.

## Consequences

- Agent and Interaction code can remain stable as new inference services are added.
- The framework owns a small, typed Provider surface instead of inheriting a vendor SDK's public model.
- OpenAI compatibility provides familiar defaults while explicit capabilities prevent false portability claims.
- Reviewer and Verifier structured output can use the same Provider boundary as participant Agents.
- vLLM users receive tested support for structured output, reasoning, and Tool calling without installing vLLM into the core project environment.
- vLLM support requires maintaining a versioned real-server compatibility profile and access to a suitable integration environment.
- Some model/server combinations will correctly fail preflight even though other vLLM models support the requested feature.
- Reasoning increases native Trace size and may contain sensitive data, so its retention and export boundary must remain visible.
- Non-streaming Chat Completions is deliberately narrower than the full OpenAI and vLLM APIs; streaming and Responses support can be added without changing the semantic Provider protocol.

## References

- [ADR-0001](./0001-data-generation-first-agent-trace-architecture.md)
- [ADR-0003](./0003-compile-one-run-plan-per-seed.md)
- [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md)
- [ADR-0006](./0006-support-responses-and-chat-completions-with-pydantic-structured-outputs.md)
- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create)
- [vLLM structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)
- [vLLM reasoning outputs](https://docs.vllm.ai/en/latest/features/reasoning_outputs/)
- [vLLM Tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/)
