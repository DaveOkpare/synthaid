# 03: Use the shared OpenAI-compatible transport for vLLM

Type: implementation
Status: resolved
Blocked by: 02

## Description

Revised after the user's Task 02 review on 2026-10-01. The library calls an external vLLM OpenAI-compatible HTTP server. A server-certification framework is outside the requested scope. Task 02 is a completed relocation checkpoint, not the final provider design.

Reuse `ChatCompletionsProvider` / `ResponsesProvider` for the selected API and base URL. A minimal Chat Completions task already works with `type = "openai-compatible"`, `api = "chat_completions"`, and a base URL, without profiles or conformance imports; this was verified through offline task loading, provider selection, generation, and persisted Trace loading.

Remove the packaged conformance harness, its synthetic lookup/answer fixtures, and runtime certification gates. Keep existing data-generation Python names and task fields through minimal compatibility translation. `type = "vllm"` should select the shared transport and default to Chat Completions; an old profile may remain readable as metadata but must not be required to connect. Native request options converge at one bounded JSON mapping in the shared wire path. This compatibility checkpoint retains the existing typed fields instead of introducing a new public extra-body field or expanding the hierarchy.

The user authorized removing the integration provider/conformance files and packaging the startup command on 2026-10-01. Retiring conformance-only commands/helpers is an explicit exception to the previous broad compatibility inventory. Preserve the generation API, legacy task readability, saved artifacts, and useful behavior tests. Amend ADR-0005/0006/0007 when implementing the new provider decision.

## Acceptance criteria

- [x] Both selected OpenAI API transports can call a configured compatible endpoint without a conformance report, hardware/version profile, or imported vLLM engine.
- [x] The live conformance harness, `_LOOKUP`, `_Answer`, native-mode test-case builders, and certification/report-digest gates are removed from shipped execution code. Ordinary transport/schema/tool tests remain in the test suite.
- [x] Existing `VllmProvider` / `type = "vllm"` generation entry points use the same transport implementation; legacy task options retain wire meaning through a small compatibility translation.
- [x] Optional native request parameters use one bounded JSON payload seam; framework-owned fields cannot be silently overridden. Reasoning remains private, structured results remain locally validated, and provider errors remain recorded.
- [x] Existing generation imports, task loading, and saved Trace loading/export remain compatible. Record intentional retirement of conformance-only entry points and changed profile-gating behavior explicitly.
- [x] Publish actual deleted versus moved lines; do not count namespace changes as deletion.

## Verification

Run existing provider, Responses, structured-output, component, import-safety, and saved-artifact tests; add a focused legacy/minimal vLLM task regression using fake HTTP transports. Update tests for intentionally retired certification behavior without dropping transport/tool/schema/privacy/error coverage. Run the full deterministic suite, lint/format, strict typing, and package checks. No live server is required for this internal simplification.

## Likely files and scope

This revision replaces the original model-relocation task. It is split before implementation into 03a shared transport, 03b packaged startup, and 03c conformance retirement/verification. Root coordinates; every implementing agent owns a review. Existing typed native options are translated at the shared wire boundary; no additional public option hierarchy or new required configuration is introduced in this checkpoint.

## Reference

[vLLM OpenAI-compatible server documentation](https://docs.vllm.ai/en/stable/serving/online_serving/openai_compatible_server/) documents the normal base-URL client path and optional extra request-body parameters. Feature availability remains a property of the served model and server configuration; the client retains local validation and normal request failures.

## Answer

Resolved 2026-10-02 following explicit user authorization to delete the integration provider/conformance files and package a short launcher command. Slices [03a](03a-shared-transport.md#answer), [03b](03b-packaged-startup.md#answer), and [03c](03c-retire-conformance.md#answer) are complete.

`integrations/vllm/` now contains only its namespace initializer and `serve.py`. The installed command is:

```sh
agentinstruct vllm --model MODEL -- agentinstruct run TASK
```

Use `--server-python` for a separate vLLM environment and configure the Task's base URL/selected API. Both HTTP APIs work through the ordinary providers; legacy generation imports/task fields remain supported by small compatibility translation. Profiles no longer authorize runtime features. The conformance-only API/CLI and synthetic cases are intentionally retired under ADR-0008. Existing typed profile metadata remains readable for saved artifacts. Local validation, private reasoning, reviewed Tool effects, safe failures, and cleanup remain protected.

All implementing agents performed their own reviews. Independent integration review caught an API mismatch regression, which was fixed and tested before completion. Final gates: **586 tests passed in 55.11s**, Ruff check, Ruff format (172 files), strict mypy (56 files), locked offline dependency check, whitespace check, wheel/sdist build and contents, built-wheel help/imports and 78-export inventory. No live model/GPU run was performed.

### Source accounting

Physical Python lines include blanks/docstrings and are counted recursively.

| Category | Task 02 / 02a shipped checkpoint | Task 03 final |
| --- | ---: | ---: |
| Core | 8,736 | 8,728 |
| Integration | 727 | 165 |
| Compatibility | 34 | 41 |
| Total shipped | 9,497 | 8,934 |

The three retired module files contained 750 lines: canonical adapter 219, canonical conformance 506, legacy conformance forwarder 25. Necessary native option translation/reasoning behavior was consolidated into shared code, rather than counted as eliminated behavior. The 163-line startup script moved into the wheel and is fully included in the new total. Net shipped reduction is **563 lines**, or **506 lines below the original 9,440-line baseline**. The 41-line legacy module preserves generation constructors; it contains no parallel transport implementation. Final source is 31 Python files; all 78 original top-level exports remain.

Task 04 and later ownership/refactor stages remain unstarted for their code-review checkpoints.
