# 02: Isolate vLLM execution

Type: implementation
Status: resolved
Blocked by: 01

Start gate: Approved by the user's “you can proceed” after Task 01 code review on 2026-10-01. Only Task 02 is being executed before the next code review.

## Description

Move the existing vLLM adapter and live-conformance implementation into `integrations/vllm/`. Preserve the existing imports and module command through forwarding entry points in the same distribution.

## Acceptance criteria

- [x] `VllmProvider` and the old conformance command delegate to exactly one relocated implementation; no GPU/network work happens at import.
- [x] Existing vLLM Tasks, transport injection, capability checks, errors, and conformance output retain behavior.
- [x] Ordinary OpenAI generation does not import the vLLM adapter/conformance implementation; record relocated and deleted lines separately.

## Verification

Run `uv run --locked pytest tests/test_vllm.py tests/test_providers.py tests/test_import_safety.py` and focused lint/type checks. Check conformance help offline and package module inclusion; do not run live inference.

## Likely files and scope

Medium: logical moves of `vllm.py` and `vllm_conformance.py` to `integrations/vllm/provider.py` and `integrations/vllm/conformance.py` with old-path forwarders; `providers.py`; existing vLLM tests. Source digests may change; public error categories and field shapes do not.

## Answer

Completed on 2026-10-01 after explicit user approval. Tasks 03–10 were not started.

- Provider implementation lives in `src/agentinstruct/integrations/vllm/provider.py`; its 219 original lines are byte-for-byte unchanged. `providers.create_provider()` imports it only when vLLM is selected.
- Conformance implementation lives in `src/agentinstruct/integrations/vllm/conformance.py`. The old modules forward to the same public objects and the old module command still runs. Imported reports retain `agentinstruct.vllm_conformance:_Answer`; module-command reports retain `__main__:_Answer`. The legacy command restores shared schema metadata on exit.
- The top-level facade lazily resolves only `VllmProvider`, retaining all 78 exports, direct imports, and discovery through `dir()`. Integration namespace initializers import no execution code.
- `tests/test_import_safety.py` blocks both old/new vLLM execution imports during package startup, validation, and real Runner regressions for both OpenAI APIs. It also checks alias identity, import effects, and CLI report identity without live inference.

Delegated provider and conformance agents reviewed their own changes; an independent reviewer found the CLI provenance discrepancy, verified its fix, and reported no remaining actionable findings.

Verification: final full suite **557 passed**; lock check, whole-repository Ruff lint/format, strict mypy (57 source files), and wheel/sdist build passed. Both packaged module commands passed offline `--help`; archives contain canonical implementations, legacy entry points, and `py.typed`, and exclude scratch/tasks/run outputs. No live server or GPU checks were run.

Size accounting (physical Python lines, including blanks/docstrings):

| Measure | Before | After |
| --- | ---: | ---: |
| Total shipped source | 9,440 | 9,497 |
| Python source files | 29 | 33 |
| Integration namespace | 0 | 727 |
| Forwarding-only compatibility files | 0 | 34 |
| Remaining core | 9,440 | 8,736 |

**721 implementation lines relocated; zero implementation lines deleted.** The 727 integration lines include two namespace docstrings and four schema-identity compatibility lines. Forwarders add 34 lines and the lazy facade adds 17, giving **57 net additional lines**. This ticket establishes the execution boundary; it does not claim a smaller distribution. vLLM schemas and shared request validation remain for Task 03.
