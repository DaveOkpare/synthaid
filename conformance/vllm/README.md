# External vLLM conformance

**No real-server compatibility claim has been established.** The bundled
`qwen3-1.7b.json` is an **unverified candidate**, not a library default. Its version,
model revision, tokenizer template and parsers are pinned for a future operator
run. No GPU server was available during implementation, and no inference engine
is installed by `agentinstruct`.

The candidate uses vLLM `0.30.0` and `Qwen/Qwen3-1.7B` revision
`70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`. It requests the tokenizer's embedded
`chat_template` at that same revision, the `qwen3` reasoning parser, `hermes` Tool
parser, automatic Tool choice, and the `xgrammar` structured backend. An operator
must provision the server independently and include every actual additional
launch flag in a copy of the candidate. Hardware is operator-attested provenance;
the harness does not invent or infer it from an endpoint.

Run the suite only against an already configured server:

```sh
uv run python -m agentinstruct.vllm_conformance \
  --allow-live \
  --profile conformance/vllm/qwen3-1.7b.json \
  --base-url http://localhost:8000/v1 \
  --hardware 'actual GPU model/count, precision, driver/runtime' \
  --api chat_completions \
  --output /tmp/qwen3-chat-conformance.json
```

For authentication, add `--api-key-env VLLM_API_KEY`; the resolved value is never
written to the report. Do not put credentials in server flags. The command requires
`--allow-live` even when inference-related environment variables are already set.
Ordinary pytest, import, package validation, and test collection cannot start this
suite. The report path must be new. The suite does not download models, launch a
server, retry requests, or switch API surfaces.

The harness verifies `/version` and `/v1/models`, then preflights every declared
case before its first generation call. It checks text, each declared portable and
native structured mode, Pydantic local parsing, each Tool-choice mode, ordered
multiple calls when declared, Tool-result continuation using fresh markers,
reasoning separation, each declared reasoning control/modifier, and every declared
combined-feature case. Semantic mismatches and typed Provider errors fail cases.
Controls are tested with the recorded fixture values; a passing report is evidence
for that request profile, not every possible value accepted by a server. The
candidate includes reasoning plus JSON Schema/JSON object/regex/Tools and does not
claim parallel Tool calls or a Responses surface.

Each report records the Provider Plan (including version, revision, flags, parsers,
template, request defaults and hardware), selected API, observed server version
and model, timestamps, exact per-case semantic requests, per-case results, and a
canonical SHA-256 digest. The
`run_conformance` Python seam can use deterministic injected transports; such
reports explicitly say `injected_transport` and are **not live compatibility
evidence**. A release claim requires `execution = "live"`, `passed = true`, the
observed server probes, and a retained report for the exact profile. Change any
model, revision, server configuration, hardware or requested feature combination
and rerun the suite.

After a real pass, the operator can copy the profile into Task configuration and
set that surface's `conformance = "passed"` and `report_digest` to the report's
`digest`. These fields are an operator declaration referencing retained evidence;
runtime inference does not fetch or independently authenticate a report. The
repository's candidate stays unverified until actual evidence is reviewed.

Responses requires its own explicitly declared candidate surface and its own
`--api responses` run. The harness alone can probe an unverified Responses
candidate; ordinary `VllmProvider` construction and Task validation reject that
surface until its separate passed declaration includes a report digest. A Chat
pass cannot enable Responses. Endpoint contradictions are typed errors.

Primary configuration references:

- [vLLM 0.30.0 release](https://github.com/vllm-project/vllm/releases/tag/v0.30.0).
- [Pinned structured outputs](https://docs.vllm.ai/en/v0.30.0/features/structured_outputs/): current `structured_outputs` fields, no removed `guided_*` options.
- [Pinned reasoning controls](https://docs.vllm.ai/en/v0.30.0/features/reasoning_outputs/): `reasoning`, `include_reasoning`, thinking budget and template controls.
- [Pinned Tool calling](https://docs.vllm.ai/en/v0.30.0/features/tool_calling/), plus [Qwen's vLLM deployment guide](https://qwen.readthedocs.io/en/latest/deployment/vllm.html) for Qwen3's `qwen3`/`hermes` parser configuration. Historical request-field names in Qwen examples are not used.
- [Pinned Harmony parser implementation](https://docs.vllm.ai/en/v0.30.0/api/vllm/parser/harmony/) accepts the `structures`/`triggers` inner structural-tag JSON shape. The adapter sends its serialized string under current `structured_outputs.structural_tag`, not the removed top-level field.

These references justify a candidate configuration, not a tested compatibility
claim. Broader modes (JSON, choice, regex, grammar, JSON object, structural tags)
are available as typed adapter options and deterministic contracts; they require
explicit profile declarations and live evidence before being advertised for a
particular server/model pair.
