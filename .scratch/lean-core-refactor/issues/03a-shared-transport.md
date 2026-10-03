# 03a: Share the two HTTP transports with vLLM

Type: implementation
Status: resolved
Blocked by: 02

## Description

Use ordinary Chat Completions/Responses transports for `type = "vllm"`, requiring only its base URL. Keep legacy generation constructors and task fields. Profiles remain readable metadata; remove model/version/report gates. Native options retain wire meaning through common translation and local validation. Preserve private reasoning, tool parsing, JSON validation, and safe errors.

## Scope

Five logical units: shared transport (`providers.py`); authoring validation (`task_config.py`); legacy adapter replacement/removal (`vllm.py` and deleted `integrations/vllm/provider.py`); public lazy import (`__init__.py`); behavior tests (`test_vllm.py`, `test_responses.py`). Separate agents own implementation and behavior tests. No Plans schema expansion in this checkpoint.

## Verification

Focused provider/Responses/native-options tests, each agent's self-review, then root integration checks.

## Answer

Resolved 2026-10-02. The ordinary Chat Completions/Responses factory now serves legacy vLLM selectors and compatible endpoints without profile/model/combination/report gates. Legacy `VllmProvider` is 41 lines of constructor/helper compatibility; integration `provider.py` is deleted. Native typed options use the shared `option_body` JSON mapping, with local output/schema/effort conflicts preserved. No new public extra-body field or option hierarchy was introduced in this checkpoint. Profiles remain optional readable metadata; existing metadata dataclasses retain their prior shape validation for saved records.

Private Chat reasoning and its legacy alias use the common normalizer; malformed values and unparsed Tool intent fail safely. Schema compilation/callbacks, credential scrubbing, provider error evidence, Tool acceptance rules, and persisted formats remain covered. A review found and fixed direct constructor/Plan API mismatch: both directions fail before HTTP rather than changing the selected API.

Implementing and test agents each performed their own review; a separate read-only review confirmed the fix and found no remaining actionable issues. Adapted transport suites pass 89 tests; final aggregate quality gates are recorded in the parent answer. Only conformance-only tests were removed; ordinary behavior coverage expanded.
