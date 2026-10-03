# Refactor compatibility baseline

> Historical inventory. ADR-0008 retired conformance-only paths; [ADR-0009](../../docs/adr/0009-remove-unused-import-compatibility.md) subsequently retired unused provider/inspection/facade aliases. The current facade has 76 exports. The original 78-name inventory below no longer requires retaining unused compatibility code.

Baseline commit: `4c5044264d09706f7c4905295191f52eae23fe8b`. Contract: preserve current Python API, Task Packages, CLI, and saved Traces. The pinned source is the exact constructor/signature/field reference; the tables below identify the surfaces and existing behavior tests rather than documenting every internal helper.

| Measurement | Before refactor |
| --- | ---: |
| Python source files | 29 |
| Physical source lines | 9,440 |
| Class definitions | 159 |
| Top-level exports | 78 |

Count `src/agentinstruct/**/*.py`; exclude tests and `py.typed`. Later stages report total, core, integration/UI, and forwarding lines separately. Relocation does not count as deletion.

## Python surfaces

All 78 names in [`agentinstruct.__all__`](../../src/agentinstruct/__init__.py) remain importable:

| Family | Current exports | Existing coverage |
| --- | --- | --- |
| Caller/lifecycle | `TaskPackage`, `TaskValidationError`, `Runner`, `generate`, `generate_sync`, `RunResult` | `test_runner`, `test_collections`, `test_release_workflow` |
| Agent/Environment | `Agent`, `Agents`, `Environment`, `Observation`, `TaskContext` | `test_components`, `test_dialogue`, `test_steps` |
| Component lookup | `BUILTIN_COMPONENTS`, `ComponentError` | `test_components`, `test_import_safety` |
| Plans/Seeds | `RunPlan`, `ModelPlan`, `ProviderPlan`, `ReviewerPlan`, `VerifierPlan`, `ToolPlan`, `StepPlan`, `StepAgentPlan`, `Seed`, `SeedOrigin` | `test_seed_sources`, `test_collections`, `test_steps` |
| Conversation/evidence | `Message`, `FunctionCall`, `ToolCall`, `TraceSnapshot`, `VerificationAttempt` | `test_tools`, `test_verification`, `test_release_workflow` |
| Review/Verification | `Criterion`, `Rubric`, `Reviewer`, `ReviewRequest`, `ReviewResult`, `DeterministicReviewer`, `Verifier`, `VerificationResult`, `DeterministicVerifier`, `reverify` | `test_review`, `test_model_quality`, `test_verification` |
| Tools | `Tool`, `ToolContext`, `ToolExecutionFailure`, `FunctionTool`, `AgentTool` | `test_tools`, `test_components` |
| Provider | `Provider`, `ProviderCapabilities`, `SurfaceCapabilities`, `ProviderError`, `ProviderRequest`, `ProviderResponse`, `ChatCompletionsProvider`, `ResponsesProvider`, `Usage`, `InferenceControls`, `NamedToolChoice`, `ResponseFormat` | `test_providers`, `test_responses` |
| Structured/reasoning/compatible endpoint | `JsonSchemaSpec`, `StructuredOutputPlan`, `StructuredOutputValidationError`, `compile_structured_output`, `ReasoningControls`, `ReasoningItem`, `ReasoningContinuation`, `CompatibleEndpointProfile`, `CompatibleSurface` | `test_structured_output`, `test_responses`, `test_vllm` |
| vLLM | `VllmProvider`, `VllmOptions`, `VllmProfile`, `VllmSurface`, `VllmChatTemplateKwargs`, `VllmStructuredOutputs` | `test_vllm` |
| Recorded-data access | `load_trace`, `load_run`, `export_native`, `export_openai`, `Inspector`, `InspectionSession`, `RecordedRun`, `RecordedTrace` | `test_inspection`, `test_verification`, `test_release_workflow` |

Keep existing import locations used by extensions and tests: `execution` (including `AgentHandle`, `Interaction`, built-in Environments and `TurnResult`), `plans`, `traces`, `review`, `verification`, `tools`, `providers`, `model_agent`, `task_package`, `store`, `inspection`, `vllm`, and `cli`. Preserve documented `python -m agentinstruct.vllm_conformance`. Forwarding may change class implementation location; it must not break these imports or object behavior.

| Signature/hook | Contract to preserve | Existing coverage |
| --- | --- | --- |
| `TaskPackage.load(path)` | `compile`, `validate`, `seed_records`, and `compile_records` take keyword-only `seed_path=None`, `seeds=None`; the two sources are mutually exclusive. `compile` requires exactly one record. | `test_seed_sources`, `test_collections`, `test_cli` |
| `Runner(*, output_dir="runs", …)` | Keep `agent_factory`, `provider_factory`, `environment_factory`, `verifier_factory`, `reviewer_factory`, `tool_factory`; each receives its existing Plan. `run(package, *, seed_path=None, seeds=None, fail_fast=False)`. | `test_components`, `test_runner`, `test_collections` |
| `generate` / `generate_sync` | Same package/source/fail-fast inputs plus keyword-only `runner=None`; sync wrapper rejects a running event loop. | `test_runner`, `test_collections`, `test_release_workflow` |
| Custom Agent/Environment | Async `generate(observation) -> Message \| list[Message]`; async `setup(agents)` and `run(task, agents)`; optional async `finalize(task, trace)`. `Agents[id].interaction(task)` is an async context manager exposing `turn(incoming=None)` and `control(proposal)`. | `test_components`, `test_dialogue`, `test_steps`, `test_verification` |
| Custom components | Explicit `module:Class`; Agent/Reviewer/Verifier/Tool constructors receive the existing Plan, Environment constructor takes no arguments. Keep nested attributes and valid static/class methods. Function Tool reference takes async `(arguments, context)`; Agent Tool factory takes synchronous configuration and returns a fresh Agent. | `test_components`, `test_tools` |
| Review/Verification/Provider | Async `review(request)`, `verify(trace)`, `generate(request)`; Provider exposes capabilities and async `aclose()`. Keep result validation, weighted scoring, and surface-specific preflight. | `test_review`, `test_model_quality`, `test_verification`, `test_providers`, `test_responses` |
| Saved-data functions | Exporters keep `(traces, destination, *, statuses={"accepted"}, verification_id=None, run_ids=None, trace_ids=None, seed_ids=None) -> int`. `load_trace` keeps attempt selection; `reverify` keeps Plan/package, verifier/provider factory and Provider Plan overrides. | `test_verification`, `test_release_workflow`, `test_inspection` |

Import, CLI help/version, and offline validation must not initialize clients, use the network, or write Run storage (`test_import_safety`). The later isolation stage strengthens this to avoid importing integration execution/TUI code on ordinary core paths; current no-effect tests alone do not prove that separation.

## Task syntax and defaults

Preserve `schema_version = "1"` and the existing `[task]`, `[seed]`, `[variables]`, `[providers.<id>]`, `[model]`, `[agents.<id>]`, `[environment]`, `[runtime]`, optional `[tools.<id>]` and `[verifier]` declarations. Keep `module:attribute` references and typed endpoint/vLLM fields.

| Contract | Existing coverage |
| --- | --- |
| Required `agents/<id>/instruction.md`; configured Review adds `reviewer.md` and `rubric.toml`; final Verification uses `verifier/rubric.toml` and model Verification also requires `verifier/instruction.md`. Strict, sandboxed templates bind declared dot-path Variables. | `test_package_safety`, `test_components`, `test_hardening`, `test_model_quality` |
| One explicit Target; dialogue uses `user` and `assistant`. Ordered `[task] steps` use `steps/<step>/agents/<id>/instruction.md` and optional appended rubric. Current-step additions replace previous additions; accepted history persists. | `test_dialogue`, `test_steps` |
| JSON object/array, JSONL, CSV, directory+required glob, and Python iterable sources; stable identities/origins; optional local JSON Schema; records compile independently. | `test_seed_sources`, `test_collections` |
| Default Agent `type="model"`; model overrides inherit Task defaults; model Reviewer inherits Agent defaults. OpenAI defaults to Responses; compatible/vLLM to Chat Completions. No silent API fallback. Reasoning retained by default. | `test_providers`, `test_responses`, `test_model_quality`, `test_vllm` |
| Review `max_revisions=1`, conversational exhaustion fallback disabled; rubric threshold `1.0`, criterion weight `1.0`; Tool errors default to `fail`; final Verification timeout `60.0`. | `test_review`, `test_tools`, `test_verification`, `test_model_quality` |
| Local-only runtime; single `max_turns=1`; dialogue initiator `user`, `max_rounds=10`; no default Environment timeout. No Verifier means `unverified`. Fresh state per Trace; sequential Seeds; fail-fast stops only `invalid` or `failed`. | `test_runner`, `test_dialogue`, `test_collections`, `test_hardening` |

## CLI and saved formats

`agentinstruct` keeps `--help`, `--version`, and no-command help. Preserve every existing option:

| Command | Options | Exit behavior / existing coverage |
| --- | --- | --- |
| `validate package` | `--seed`, `--json` | Valid `0`, invalid `2`; `test_cli` |
| `run package` | `--seed`, `--output` (default `runs`), `--json`, `--fail-fast` | Success `0`; failed/invalid attempts or source/storage failure `1`; invalid package `2`; `test_cli`, `test_release_workflow` |
| `export traces…` | `--format` (`openai` default / `native`), required `--output`, repeatable `--status`, `--run-id`, `--trace-id`, `--seed-id`, `--verification`, `--json` | Success `0`, export failure `1`; accepted default; `test_cli`, `test_release_workflow` |
| `reverify traces…` | `--package`, `--json` | Valid decision `0` including rejected; unverified/error `1`; invalid override package `2`; `test_cli`, `test_verification` |
| `inspect path` | `--json` or `--tui`, `--trace` (1-based), `--view`, `--participant` | Success `0`, inspection error `1`; preserve existing views and terminal navigation; `test_inspection` |

Unknown arguments remain argparse exit `2`. Preserve JSON result keys and text behavior; TUI extraction retains the entry point.

Saved Run layout remains `source-task/`, `manifest.json`, `traces.jsonl`, and `traces/<id>/` containing `run-plan.json`, `trace.json`, `conversation.jsonl`, `events.jsonl`, `verification/<attempt>.json`, `artifacts/`. No saved-schema version change is planned.

| Recorded contract | Existing coverage |
| --- | --- |
| `TraceSnapshot`: schema/run/trace/seed identities, status, generation outcome, Run Plan, conversation, Events, component provenance, timing, Verification attempts/selection, optional invalid-seed evidence and Task identity. | `test_runner`, `test_collections`, `test_release_workflow` |
| `MessageCommit`: message, turn/time/step, shared/private visibility, causal/review references and exhaustion flag. OpenAI-shaped Message/Tool fields keep their JSON representation. Review precedes durable intent; intent precedes Tool effect; result precedes next proposal. | `test_tools`, `test_review`, `test_steps` |
| Events retain drafts, Review, model-call and failure evidence; simulator Tools and reasoning remain private. Provider surface, schemas, controls and safe provenance remain recorded; secrets remain scrubbed. | `test_providers`, `test_responses`, `test_model_quality`, `test_hardening` |
| Terminal statuses: `accepted`, `rejected`, `unverified`, `invalid`, `failed`. Native snapshots remain complete away from the source package/Run. Reverification appends sidecars without changing sealed generation; failed generation cannot be promoted. | `test_verification`, `test_release_workflow`, `test_inspection` |
| Training export uses accepted target-facing messages by default; preserves structured Tool calls, source order and selection; protects source evidence from overwrite. | `test_tools`, `test_verification`, `test_package_safety`, `test_release_workflow` |

## Verification record

- Pre-change deterministic baseline (root agent): **552 passed in 48.38s**. Command: `uv --cache-dir /private/tmp/agentinstruct-refactor-uv-cache run --locked --offline pytest`. No pre-existing failures.
- Task 01 added [two historical-artifact regressions](../../tests/test_refactor_compatibility.py) and an [unaltered old Trace/Verification fixture](../../tests/fixtures/compatibility/README.md), captured offline from the baseline commit. Existing tests retain live extension/signature coverage; no new private-structure snapshots were introduced.
- Focused compatibility/release/components/CLI/import checks: **55 passed**. Post-change full deterministic suite: **554 passed in 48.89s**.
- Lock consistency, whole-repo Ruff lint/format, strict mypy (**53 files**), source/wheel build, package contents, and local documentation links pass. Independent read-only review found no actionable issues. Production source remains at **9,440 lines**; Task 01 establishes guardrails rather than performing deletions.
- User approval is required before Task 02 starts; no later ticket has begun.

See [Task 01](issues/01-record-compatibility-baseline.md), the [spec](spec.md), [interface sketch](interfaces.md), and [ADR-0007](../../docs/adr/0007-agent-owned-review-and-lean-core.md).
