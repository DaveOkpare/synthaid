# Doubleword realtime inference for an agentinstruct smoke

Research date: 2026-09-30. External sources are official Doubleword documentation and policy pages. Local compatibility observations come from the existing agentinstruct implementation. This note records **documented behavior, not live-test results**: its author made no authenticated API requests or inference calls. Account-visible availability, actual costs, and successful feature combinations require separate live evidence.

## Recommendation

Use `Qwen/Qwen3.5-9B` for inexpensive **initial text connectivity** through the existing `openai-compatible` Provider with `api = "chat_completions"`, base URL `https://api.doubleword.ai/v1`, and `DOUBLEWORD_API_KEY` as the credential environment-variable name. Request `reasoning_effort: "none"` for the first bounded, text-only smoke. This model documents a realtime tier, a 262K native context, and explicit thinking disablement; other effort settings enable thinking without graduated levels. This does not establish reliable Tool use or clinical accuracy; see the model-specific Tool warning below. [Qwen3.5-9B](https://docs.doubleword.ai/inference-api/models/qwen-qwen3-5-9b)

Candidate prices below are **USD per million tokens**, using realtime prices rather than async/batch discounts. Availability is limited; a catalog entry is not proof that this account can invoke it now.

| Exact model ID | Input | Cache read | Output | Selection consideration |
|---|---:|---:|---:|---|
| `Qwen/Qwen3.5-9B` | $0.10 | $0.02 | $0.15 | Initial text connectivity: low output price and explicit non-thinking mode; documented Tool reliability limitation. |
| `openai/gpt-oss-20b` | $0.03 | $0.02 | $0.13 | Cheaper token prices, but documented effort choices are only low/medium/high. |
| `Qwen/Qwen3-VL-30B-A3B-Instruct-FP8` | $0.15 | $0.04 | $0.60 | Alternative instruct model; its page does not advertise reasoning controls. |
| `Qwen/Qwen3.6-35B-A3B-FP8` | $0.14 | $0.14 | $1.00 | Candidate for the full Tool workflow based on Doubleword's Rig tests; reasoning-control documentation conflicts. |

Prices: [model catalog](https://docs.doubleword.ai/inference-api/models). IDs/capabilities: [Qwen3.5-9B](https://docs.doubleword.ai/inference-api/models/qwen-qwen3-5-9b), [Qwen3-VL-30B](https://docs.doubleword.ai/inference-api/models/qwen-qwen3-vl-30b-a3b-instruct-fp8), [GPT-OSS-20B integration](https://docs.doubleword.ai/inference-api/integrations/supermemory), [reasoning support table](https://docs.doubleword.ai/inference-api/reasoning-controls). Qwen3.5-4B has no realtime price/tier in the catalog; its cheaper batch price is not a realtime substitute.

For scale intuition, 100,000 uncached input tokens plus 10,000 output tokens on Qwen3.5-9B would cost about **$0.0115**, calculated from the listed rates. Actual billing can differ with cache reuse and usage across generation, review, revision, and verification calls.

## Endpoint, authentication, and limits

- Send synchronous `POST https://api.doubleword.ai/v1/chat/completions`, with `Authorization: Bearer <key>` and JSON content. Standard OpenAI clients work with the custom base URL. The realtime Chat examples omit `service_tier`; the official PR-review workbook explicitly identifies realtime as the default. The Responses examples use `service_tier: "priority"`. [Realtime guide](https://docs.doubleword.ai/inference-api/realtime-inference), [tier comparison](https://docs.doubleword.ai/inference-api/pr-review-bot)
- Self-serve realtime uses shared, rate-limited capacity intended for development/testing. The reviewed public pages do not establish an account-specific RPM, TPM, concurrency cap, request-body limit, or deployed context limit. Keep the smoke sequential and bounded; do not treat batch limits as realtime limits. Dedicated production capacity is a separate offering. [Inference overview](https://docs.doubleword.ai/inference-api/intro-to-doubleword-inference)
- Chat accepts `max_completion_tokens`, or legacy `max_tokens`. Reasoning uses `reasoning_effort`; Responses instead uses `reasoning.effort` and `max_output_tokens`. Unsupported effort values reject. Where effort maps to a fixed reasoning budget, the output limit must exceed it. Omission selects the model default. Do not send vLLM-specific `chat_template_kwargs`, `thinking`, or `thinking_token_budget`. [Reasoning controls](https://docs.doubleword.ai/inference-api/reasoning-controls)
- Keys can have one-off or recurring spending caps; the default is uncapped. Using an existing environment variable requires no SDK change. [API-key guide](https://docs.doubleword.ai/inference-api/creating-an-api-key)

For this smoke, a 512–1,024-token per-call output limit with thinking disabled is a proposed starting bound, not a documented service limit. Keep prompts and expected outputs small enough to fit it.

## Structured output, Tools, and reasoning evidence

Doubleword documents OpenAI-style function definitions under `tools`, JSON Schema parameters, and `tool_choice: "auto"`. Its structured-output example sends `response_format.type = "json_schema"` with a named schema and `strict: true`. The examples use batch envelopes; synchronous Chat sends the envelope's `body` directly. These general documentation claims do not establish every model's support for required/named Tool choice, parallel calls, every schema construct, or combinations with reasoning. Test the exact combination needed. [Tools and structured outputs](https://docs.doubleword.ai/inference-api/tool-calling)

**Model-specific warning:** Doubleword's Rig guide reports that Qwen3.5-9B sometimes answered question-shaped extraction prompts in prose instead of emitting the required Tool call. Its tests found Qwen3.6-35B-A3B and larger models reliable for that extraction workflow. The example uses required Tool choice through Responses on the flex tier, so this is relevant model evidence, not proof of our exact realtime Chat workflow. The guide recommends retaining small models for free-text drafting. [Rig: picking the extractor model](https://docs.doubleword.ai/inference-api/integrations/rig)

`Qwen/Qwen3.6-35B-A3B-FP8` is therefore a documented candidate for a separate realtime Tool probe; its page lists realtime at $0.14/M input and $1.00/M output. The same page says reasoning-effort parameters have no effect, then lists all efforts from `none` through `max` as supported. The general reasoning guide also lists these efforts. This contradiction leaves actual thinking disablement unresolved; validate the requested setting and returned behavior rather than promising it. [Qwen3.6-35B-A3B](https://docs.doubleword.ai/inference-api/models/qwen-qwen3-6-35b-a3b-fp8), [reasoning controls](https://docs.doubleword.ai/inference-api/reasoning-controls)

For a cheaper alternative, the Supermemory integration explicitly identifies `openai/gpt-oss-20b` as capable of Chat function calling. Its realtime availability is listed separately in the catalog; the documented integration itself uses flex, so an actual realtime Tool probe remains necessary. [Supermemory integration](https://docs.doubleword.ai/inference-api/integrations/supermemory), [model catalog](https://docs.doubleword.ai/inference-api/models)

The reviewed reasoning guide specifies request controls but does not establish a universal Chat response field (`reasoning` versus `reasoning_content`) or replay contract. Record actual returned field names separately if reasoning is later tested; do not infer a vLLM parser/profile from the model family.

## Existing adapter fit and boundaries

These observations are from [providers.py](../src/agentinstruct/providers.py), [plans.py](../src/agentinstruct/plans.py), and the constraints in [ADR-0005](../docs/adr/0005-use-an-openai-shaped-provider-protocol-with-vllm-conformance.md) and [ADR-0006](../docs/adr/0006-support-responses-and-chat-completions-with-pydantic-structured-outputs.md):

- The Chat adapter already sends Bearer authentication, function Tools, JSON Schema response formats, `reasoning_effort`, and `max_completion_tokens` (mapped from framework `max_tokens`). It requests one non-streamed choice and does not send `service_tier`. No new Provider architecture is needed for the initial smoke.
- The generic Chat normalizer ignores unknown wire fields. It does **not** extract private reasoning text, although it can record `usage.completion_tokens_details.reasoning_tokens`. Its `retain_reasoning` flag cannot recover discarded fields. Thinking-disabled requests therefore provide a narrower and more accurate initial compatibility claim.
- Framework Messages are text-only here despite the model's vision capability. The portable effort enum also excludes Doubleword's `max`; the recommended `none` value is supported locally.
- Local structured-output validation remains mandatory; malformed JSON, schema mismatch, refusals, and incomplete output remain failures even if the service advertises strict decoding. Each Tool call also needs a stable ID and JSON object arguments.
- Requests include `store: false`, `stream: false`, and `n: 1`; acceptance of the complete serialized request still needs a live check. `store: false` must not be equated with Doubleword account-level ZDR.
- The adapter has no retries or async/background polling, and defaults to a 60-second HTTP timeout. Generic-compatible Responses requires an explicitly passed conformance profile. Stay on Chat for this smoke; do not invent a passed Responses/vLLM profile.
- Cache-read/write detail fields are not normalized into framework `Usage`. Doubleword documents implicit caching and cache usage fields, so price estimates from the stored basic token totals are estimates rather than exact billing. [Prompt caching](https://docs.doubleword.ai/inference-api/prompt-caching)

## Data handling for medagent Seeds

The current policy prohibits personal data without written agreement and any required DPA, and separately prohibits highly sensitive personal data including health data. Use genuinely synthetic, non-personal Seed content; removing contact fields alone does not establish this. Default prompt/input/output content is retained in persistent storage and queues in AWS Europe via Neon; GPU processing may occur across regions. ZDR is **opt-in**, applies only to eligible realtime/async endpoints, and still retains operational metadata. No fixed default content-retention period is stated. The policy announces no model training without opt-in, while its detailed section includes an operational-service exception. [Data Usage Policy, updated 2 July 2026](https://doubleword.ai/data-usage-policy/)

This research did not verify the account's ZDR setting or find a documented request flag that enables it. A live report should separately record the non-personal Seed selection, exact model, requested controls, observed model/usage/finish metadata, and which text/JSON/Tool behaviors actually passed. It should not claim clinical validity or general endpoint conformance from a small smoke.
