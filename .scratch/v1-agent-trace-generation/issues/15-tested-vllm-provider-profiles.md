# 15: Add tested vLLM Provider profiles

**What to build:** Let operators configure an external vLLM server as a first-class tested Provider profile for documented structured-output, reasoning, and Tool-calling workflows.

**Blocked by:** 14 — Add Responses API parity and private reasoning

**Status:** resolved

**Claimed by:** ticket15

**Type:** implementation

- [x] vLLM remains an external OpenAI-compatible service and is not a mandatory core Python dependency.
- [x] The vLLM profile defaults conservatively to Chat Completions and allows Responses only when that surface is explicitly declared conformant.
- [x] Typed vLLM options cover the supported current structured-output modes and reasoning controls without an unrestricted extra-body escape hatch.
- [x] Server flags, parser names, chat template, model revision, vLLM version, API Surface, request profile, and hardware class are recorded as conformance provenance.
- [x] Deterministic contract tests cover text, Pydantic-backed structured output, reasoning separation, automatic function Tool calls, Tool-result continuation, and typed failures.
- [x] An opt-in real-server suite exercises every feature combination claimed by the pinned profile.
- [x] Chat Completions conformance does not imply Responses conformance, and unsupported combinations fail preflight or with a typed endpoint contradiction.
- [x] The project makes no compatibility claim for a vLLM profile until its recorded real-server suite passes.


## Answer

Implemented external `VllmProvider` with immutable typed `VllmProfile`,
`VllmSurface`, `VllmOptions`, `VllmStructuredOutputs`, and
`VllmChatTemplateKwargs`. Task loading and Run Plans preserve the exact selected
API, model/revision, version, parser/template/launch/hardware/request provenance,
per-surface declarations and native defaults. Current native modes and reasoning
controls reject unknown fields, removed `guided_*` fields, untyped extra bodies,
invalid budgets and known credential-bearing launch flags. Schema nulls and nested
input snapshots remain intact. No inference engine dependency was added.

Preflight checks every used participant and quality judge against its exact model,
portable/native requirements and explicitly declared combined features before any
Agent inference. Endpoint contradictions and failures remain typed. Returned
`reasoning` is normalized privately; retention/suppression apply to Events, and
Chat Tool continuation sends accepted Messages without Responses reasoning replay.
Pydantic validation, reviewed durable Tool execution, model Verification and
reverification share the existing lifecycle.

Responses needs its own passed surface declaration and retained report digest.
Generic compatible Responses now uses separate `CompatibleEndpointProfile` and
`CompatibleSurface` portable declarations; unprofiled compatible Responses stays
unsupported. Earlier Responses transport fixtures now declare their deterministic
fake profile explicitly, preserving all semantic assertions.

Added the explicit opt-in `python -m agentinstruct.vllm_conformance --allow-live`
harness. It probes version/model, checks every declared mode/control/modifier and
combined feature, verifies Tool-result continuation, records exact semantic
requests and per-case outcomes, and writes immutable-new report files with a
canonical digest. Injected transports are labeled and cannot constitute live
compatibility evidence. The pinned vLLM 0.30.0 / Qwen3-1.7B candidate remains
**unverified**: no endpoint or GPU was provided, so no live suite was run and no
server/model compatibility claim is made. Hardware must be supplied by an actual
operator. See [conformance instructions](../../../conformance/vllm/README.md) and
[Provider usage](../../../README.md#use-explicit-vllm-and-compatible-endpoint-profiles).

Validation: 220 focused Provider/quality/Responses/structured/CLI/import tests
passed; 43 vLLM cases passed again after the native-schema null-preservation
regression. Strict mypy, Ruff, and `git diff --check` pass. Full-suite/build remain
reserved for ticket 19.

Review follow-up: Provider defaults now resolve without reconstructing an already
normalized structured request. Public transport regressions preserve both typed
Pydantic results and explicit JSON Schema validation with nonempty native defaults,
while genuine conflicting author inputs still fail. Conformance reasoning and
combined-feature cases explicitly request and require reasoning even when profile
defaults suppress it; the separate suppression case remains covered. All 46 vLLM
tests pass after these fixes.
