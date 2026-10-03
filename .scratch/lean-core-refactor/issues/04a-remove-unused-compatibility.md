# 04a: Remove unused vLLM and inspection compatibility paths

Type: implementation
Status: resolved
Blocked by: 03, 04

## Description

The user explicitly superseded the earlier import-preservation requirement on 2026-10-02: unused modules/components should be removed, whether legacy or not. Repository search found no production caller of `agentinstruct.vllm`; the ordinary factory already selects the two shared HTTP transports. Inspection forwarding exists solely to preserve old import locations.

Delete `vllm.py`, its top-level alias, inspection's UI forwards/wildcard compatibility, and the top-level UI alias. Active UI callers use `ui.terminal`; native transport tests exercise ordinary Chat Completions/Responses. Preserve active task syntax/native request options, static inspection, CLI behavior, server startup, private reasoning, local validation, saved Trace readability, and Review before effects. Do not remove genuinely active components based only on absence of direct Python imports; task references and public extension points count as usage.

## Scope

Five logical units: static inspection cleanup; old vLLM module/public facade retirement; shared-provider behavior tests; canonical UI caller/import-safety tests; documentation/contract amendment. No Agent runtime ownership changes or deployment features in this slice. Each implementing agent performs its own review; root integrates. Preserve the cumulative uncommitted worktree for user review.

## Acceptance criteria

- [x] No compatibility-only `vllm.py`, inspection UI forwards, or top-level provider/UI aliases remain in shipped code.
- [x] Active source/tests/examples use canonical modules and ordinary transports; useful behavior coverage survives the removal.
- [x] Static/JSON inspection remains independent of UI/startup; no SDK/engine dependency or import is added.
- [x] Document intentional import retirement and revised compatibility policy. Report actual deleted lines recursively.

## Verification

Focused provider, inspection, import-safety and offline-release tests; full deterministic suite, Ruff/format, strict mypy, lock/build/archive checks. Preserve historical saved-artifact tests; no live server required.

## Answer

Resolved 2026-10-02. The usage audit showed that the vLLM wrapper was referenced only by compatibility tests; the production factory already selects the shared HTTP transports. Deleted `src/agentinstruct/vllm.py` (41 lines), its provider/capability aliases, inspection's UI/wildcard/typing forwards, and both top-level lazy aliases. No replacement wrapper was added.

Canonical terminal imports are `from agentinstruct.ui.terminal import InspectionSession, run_terminal`. Static inspection still owns Inspector/load_run/read-only rendering. vLLM requests use ChatCompletionsProvider or ResponsesProvider; active task selectors/native options and the optional server launcher are unchanged. Tests now exercise actual transports/canonical UI. Removed only the obsolete wrapper compatibility test; existing native validation, private reasoning, schema-once, Tool/privacy, provider error, quality/reverification, stream shutdown, import/collection safety, and historical Trace checks remain.

ADR-0009 records the user's explicit change from blanket import preservation to usage-based removal. README/spec/plan/index are updated; earlier checkpoint answers remain historical records. Top-level exports are intentionally reduced from 78 to 76 by retiring InspectionSession/VllmProvider aliases. Actual Task/data/CLI formats remain intact.

Both implementing agents performed their own reviews. Independent read-only review found no remaining source/example/dynamic task references to retired paths and no actionable findings.

### Verification

**596 tests passed in 59.42s**. Ruff check/format (175 files), strict mypy (57 files), locked offline dependency check, whitespace, wheel/sdist builds and content checks pass. All shipped Python bytes match source. Built-wheel smoke checks verify deleted modules/aliases are absent, 76 exports remain, static JSON inspection stays independent of UI, canonical terminal navigation works on prior offline release output, both vLLM API selectors return shared classes, and no SDK/engine import or dependency is added. No live inference was run.

### Source accounting

| Category | Task 04 | Cleanup 04a |
| --- | ---: | ---: |
| Core | 8,641 | 8,590 |
| vLLM integration | 165 | 165 |
| UI | 124 | 124 |
| Standalone compatibility | 41 | 0 |
| Total shipped | 8,971 | 8,879 |

**92 source lines deleted; none relocated**: vLLM module 41, inspection forwarding/reexports 25, public facade forwarding/aliases 26. Source has 32 Python files and is 561 lines below the original 9,440-line baseline. Active CLI and task-selected components were not treated as unused solely because their use is indirect. Task 05 and later stages remain unstarted.
