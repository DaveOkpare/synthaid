---
status: accepted
date: 2026-09-27
amends:
  - ADR-0005
---

# Support Responses and Chat Completions with Pydantic structured outputs

ADR-0005 chose an OpenAI-shaped Provider protocol but made non-streaming Chat Completions the only V1 transport and deferred the Responses API. It also described structured output only as JSON Schema on the normalized request. That is too narrow for the built-in OpenAI Provider and unnecessarily awkward for a Python-first library.

The OpenAI Responses API and Chat Completions API express related capabilities with different wire models. Chat Completions sends `messages` and places structured-output configuration in `response_format`; Responses sends `input` items and places it in `text.format`. Responses also returns an ordered output-item stream rather than a single choice Message. The framework must support both without allowing either vendor representation to become its domain model.

Python users should also be able to define a structured result once as a `Pydantic.BaseModel`, receive the validated model instance, and use the same declaration with OpenAI, vLLM, or a future Provider. JSON Schema remains the portable wire contract, but it should not be the only authoring interface.

## Decision

### Responses and Chat Completions are Provider API surfaces

The Provider boundary remains semantic and framework-owned. Each compiled Provider Plan selects one explicit API surface:

- `responses` for the OpenAI Responses API; or
- `chat_completions` for the OpenAI Chat Completions API.

The selected surface is immutable within a Run Plan and is recorded in Trace provenance. If the same endpoint must be exercised through both surfaces, the Task declares two Provider entries. The framework does not silently fall back from one surface to the other because that would change request construction, output interpretation, and reproducibility.

The transport-neutral protocol becomes:

```python
T = TypeVar("T")


class Provider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def generate(
        self,
        request: ProviderRequest[T],
    ) -> ProviderResponse[T]: ...

    async def aclose(self) -> None: ...
```

`generate` replaces ADR-0005's `complete` name because the operation is no longer tied conceptually to a completion endpoint. `ProviderRequest` and `ProviderResponse` remain framework models. OpenAI SDK response objects, Chat Completion choices, and Responses output items never cross the adapter boundary.

### The OpenAI Provider defaults to Responses

The built-in `openai` Provider uses `responses` when `api` is omitted. Users may select `chat_completions` for compatibility, migration, or a model that requires it.

The initial defaults are:

| Provider type | Default API surface | Available API surfaces |
|---|---|---|
| `openai` | `responses` | `responses`, `chat_completions` |
| `openai-compatible` | `chat_completions` | Declared by the endpoint profile |
| `vllm` | `chat_completions` | `chat_completions`, plus `responses` when the conformance profile passes |

The conservative default for generic compatible endpoints and vLLM avoids claiming that every OpenAI-shaped deployment implements Responses correctly. A tested vLLM profile may select `responses` explicitly. Defaults can change only through a later ADR because they affect trace provenance and compatibility.

A Task may define Providers as follows:

```toml
[providers.openai]
type = "openai"
api = "responses" # optional: this is the default

[providers.local]
type = "vllm"
base_url = "http://127.0.0.1:8000/v1"
api = "responses" # requires a conformant server profile
```

Models and participants continue to refer to the Provider by its Task identifier. Provider credentials and resolved secrets remain outside the Run Plan and Trace as decided in ADR-0005.

### Both surfaces map to one semantic request and response

For Chat Completions, the adapter maps accepted history to `messages`, function Tools to `tools`, Tool selection to `tool_choice`, and a structured output to `response_format`.

For Responses, the adapter maps accepted history to self-contained `input` items, function Tools to `tools`, Tool selection to `tool_choice`, and a structured output to `text.format`. Function calls and function-call outputs retain their call identifiers when translated between framework Messages and Responses items.

The Responses adapter normalizes its ordered output items into the same semantic Provider result used by Chat Completions:

- participant-visible text becomes an assistant Message proposal;
- ordered function-call items become ordered Tool calls on that proposal;
- reasoning items remain separate private Provider data under ADR-0005;
- refusals, incomplete responses, and provider errors are represented explicitly rather than parsed as ordinary content; and
- provider-native item IDs and safe metadata are retained in the native Event for auditability.

The framework supplies the complete accepted history on every V1 request. It does not use `previous_response_id` as the authoritative conversation state, and it sends `store = false` unless a later policy explicitly opts into provider-side storage. Canonical history, replay, and persistence therefore remain owned by the framework.

Only function Tools participate in V1's portable Provider contract. Responses-hosted Tools such as web search, file search, computer use, or remote MCP can perform effects inside the provider before the framework's review boundary. They remain unsupported until a later ADR defines how their proposals, effects, review, and trace events are represented.

### Pydantic models are a first-class schema authoring interface

Any API that requests a structured model result accepts either:

1. a `type[T]` where `T` is a subclass of `pydantic.BaseModel`; or
2. an explicit framework JSON Schema specification.

Users pass the model class, not an instance:

```python
from pydantic import BaseModel, ConfigDict


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    feedback: str


request = ProviderRequest(
    messages=history,
    structured_output=ReviewResult,
)
result = await provider.generate(request)

assert isinstance(result.parsed, ReviewResult)
```

The Compiler normalizes a Pydantic class into a `StructuredOutputPlan` containing:

- a stable schema name;
- the JSON Schema generated by `model_json_schema()`;
- strictness and description metadata;
- the fully qualified Python type name for provenance when available; and
- a canonical schema fingerprint.

The class object itself is runtime-only and is never serialized into `task.toml`, the Run Plan, or the Trace. A Python component may supply or register the class; the compiled Run Plan snapshots the resulting JSON Schema so a run does not depend on later mutation of the Python definition.

The Provider adapter sends only the normalized JSON Schema. Chat Completions translates it to `response_format`; Responses translates it to `text.format`; vLLM uses the selected API surface's equivalent. Provider-native structured-output modes such as regex or grammar remain typed vLLM extensions and do not pretend to produce a Pydantic instance unless a Pydantic schema was also supplied and local validation succeeds.

After generation, the framework:

1. handles refusal, truncation, and incomplete-response states before parsing;
2. decodes the candidate JSON;
3. validates it with the original Pydantic class when one was supplied;
4. places the validated `T` in `ProviderResponse[T].parsed`; and
5. retains the original assistant Message proposal and safe raw metadata for review and tracing.

Local validation is mandatory even when the provider claims strict constrained decoding. Validation failure is a typed `StructuredOutputValidationError`; it is not silently converted into an unstructured Message or automatically retried.

Pydantic can emit valid JSON Schema that a particular provider or model does not support. Provider capability preflight therefore validates the normalized schema against the selected API surface's documented subset. Known incompatibilities fail before inference; incompatibilities discovered only from the endpoint become typed unsupported-feature or invalid-request failures.

### Capabilities are declared per API surface

`ProviderCapabilities` is no longer one flat set of claims. It contains a capability profile for each supported API surface. At minimum, each profile declares:

- text generation;
- function Tool definitions and supported Tool-choice modes;
- parallel Tool-call behavior;
- JSON object and JSON Schema structured output;
- Pydantic round-trip support, derived from JSON Schema support plus local validation;
- reasoning extraction;
- supported provider-native extensions; and
- streaming support when later implemented.

The Compiler checks the selected surface, not merely the Provider type. For example, successful vLLM Chat Completions conformance does not imply vLLM Responses conformance.

### Tests cover semantic parity and real vLLM behavior

The reusable Provider contract suite runs every supported semantic feature through each declared API surface. It verifies that equivalent requests through Responses and Chat Completions normalize to equivalent framework results without requiring identical provider-native payloads.

Structured-output tests include:

- direct JSON Schema input;
- a simple `BaseModel` round trip;
- nested models, lists, enums, aliases, nullable fields, and forbidden extras;
- schema fingerprint stability;
- refusal and incomplete output;
- invalid JSON and schema mismatch;
- unsupported JSON Schema constructs; and
- identical parsed result types through Responses and Chat Completions.

The real vLLM conformance matrix records results separately for `responses` and `chat_completions`. A release may claim support only for the tested surface and feature combination. Before claiming vLLM Responses support, the pinned profile must pass plain generation, Pydantic-backed JSON Schema output, reasoning separation, automatic function Tool calling, Tool-result continuation, and the supported combined-feature cases through `/v1/responses`.

The matrix retains the version, model revision, server flags, parsers, chat template, and hardware provenance required by ADR-0005.

## Considered Options

- **Keep Chat Completions as the only V1 surface.** Rejected because the built-in OpenAI Provider should support OpenAI's current primary generation API, and vLLM now exposes a compatible Responses endpoint.
- **Expose separate `ChatProvider` and `ResponsesProvider` protocols.** Rejected because Agents, Reviewers, and Verifiers need the same semantic operation; only the wire translation and capabilities differ.
- **Let a Provider silently choose or fall back between surfaces.** Rejected because the wire API affects behavior, supported features, and replay provenance.
- **Make Responses stateful through `previous_response_id`.** Rejected for V1 because provider-owned state would weaken local replay, accepted-history guarantees, and deterministic trace capture.
- **Expose OpenAI SDK response classes directly.** Rejected because it would couple the framework domain to one surface and complicate vLLM and future Providers.
- **Accept only handwritten JSON Schema.** Rejected because it duplicates Python types and validation logic and creates schema drift.
- **Delegate Pydantic parsing entirely to the OpenAI SDK.** Rejected because structured output must behave consistently for vLLM and Providers that do not use that SDK.
- **Trust provider-side strict decoding without local validation.** Rejected because provider implementations and supported JSON Schema subsets vary, while the framework needs one enforceable result contract.
- **Enable provider-hosted Responses Tools immediately.** Deferred because those Tools can perform effects before the framework can review the Tool-call Message as required by ADR-0004.

## Consequences

- OpenAI users get the Responses API by default while retaining explicit Chat Completions support.
- vLLM can be tested and used through both APIs without assuming feature parity.
- Agent, Reviewer, Verifier, Interaction, and Trace code continue to depend on one semantic Provider protocol.
- Python users can author structured results with `BaseModel` and receive validated typed instances.
- Pydantic becomes a required core dependency and the framework targets its V2 schema and validation APIs.
- Run Plans and Traces retain portable JSON Schema and fingerprints rather than unserializable Python classes.
- Supporting two wire APIs increases adapter and conformance-test work.
- Provider capability claims become more precise because they are scoped to an API surface.
- Stateless Responses requests may send more history than `previous_response_id` continuation, but preserve local ownership and replayability.
- Provider-hosted Tools remain unavailable until their effect and review semantics are designed explicitly.

## References

- [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md)
- [ADR-0005](./0005-use-an-openai-shaped-provider-protocol-with-vllm-conformance.md)
- [OpenAI Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [OpenAI Chat Completions API](https://platform.openai.com/docs/api-reference/chat/create)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [OpenAI migration from Chat Completions to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Pydantic JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)
