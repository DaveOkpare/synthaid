# 13: Use Pydantic structured outputs for quality gates

**What to build:** Let Python users define Reviewer and Verifier results with Pydantic models or explicit JSON Schema and receive consistently validated structured values through the Provider boundary.

**Blocked by:** 05 — Verify and reverify sealed Traces; 06 — Review and revise conversational Messages; 12 — Generate through a Chat Completions Provider

**Status:** resolved

**Type:** implementation

- [x] Structured-output APIs accept a Pydantic BaseModel subclass or an explicit framework JSON Schema specification.
- [x] Compilation produces a stable schema name, normalized JSON Schema, strictness metadata, optional qualified type name, and canonical fingerprint.
- [x] The serialized Run Plan contains the schema snapshot and fingerprint but never the Python class object.
- [x] Provider-backed Reviewer and Verifier flows receive validated typed results through Chat Completions.
- [x] Local validation remains mandatory even when the endpoint claims constrained decoding.
- [x] Refusal, incomplete output, invalid JSON, schema mismatch, and unsupported schema constructs produce distinct typed failures.
- [x] Nested models, collections, enums, aliases, nullable fields, and forbidden extras are covered by contract tests.
- [x] Malformed structured output cannot authorize a Message or produce a valid Verification score.


## Answer

Implemented immutable `StructuredOutputPlan` snapshots and `JsonSchemaSpec`
authoring alongside Pydantic BaseModel classes. Provider requests retain runtime
classes separately, snapshot the schema once, send Chat Completions JSON Schema,
and return validated Pydantic instances or immutable JSON in `parsed`. Safe typed
failures distinguish unsupported schemas, malformed JSON, schema mismatches,
refusal, and incomplete output. Duplicate keys/nonfinite values are rejected
before decoding can discard evidence; local schema, format, and strict JSON-mode
Pydantic validation remain mandatory. Offline recursive references and current
schema size limits are supported. Format-checker dependencies are uv-locked.

Model Reviewers and Verifiers use the shared typed Criterion-ID/Boolean list,
with framework-owned exact active-Rubric scoring. Model settings inherit from the
Agent for Reviewers and from the Task for Verifiers. Model Verifiers require a
strict per-Seed `verifier/instruction.md`. All used quality Providers preflight
before participant inference. Review failure cannot commit a Message or trigger
a Tool; valid rejection uses the existing private revision loop.

Verification creates fresh Provider resources and records safe call evidence plus
the actual Provider Plan in immutable attempt sidecars. Reverification from a
policy Task Package renders its instructions using the persisted Seed, including
native standalone snapshots and changed Provider endpoints. Generation bytes
remain unchanged, and later judge errors retain the previous valid decision's
export eligibility. The CLI forwards the package to this same library path.

Validation: 155 focused structured/quality/Provider/review/verification/import
checks passed, with the final JSON-boundary refinement rechecked by 92 focused
structured/Provider/model-quality tests. 148 affected Runner/Step/Tool/CLI/package
safety tests passed. Mypy, Ruff lint/format, and `git diff --check` pass. The
[offline example](../../../examples/structured-quality/run.py) produced an accepted
Trace without network inference. See [usage](../../../README.md#use-structured-quality-gates).
Full-suite/build validation remains reserved for ticket 19. Responses/reasoning,
vLLM-specific profiles, and custom import registries remain tickets 14–16.

Review follow-up: non-strict schema preflight now visits every supported schema
position, including conditional/dependency/content schemas, unevaluated schemas,
legacy tuple items, and draft-3 schema alternatives. Nested remote references and
unavailable formats fail before inference while annotations, example/default
values, enum/const data, and property-name lists remain data. All 115 focused
structured/Provider/model-quality tests pass; Mypy, Ruff, and diff checks pass.
