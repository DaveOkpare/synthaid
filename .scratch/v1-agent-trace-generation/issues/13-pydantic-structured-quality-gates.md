# 13: Use Pydantic structured outputs for quality gates

**What to build:** Let Python users define Reviewer and Verifier results with Pydantic models or explicit JSON Schema and receive consistently validated structured values through the Provider boundary.

**Blocked by:** 05 — Verify and reverify sealed Traces; 06 — Review and revise conversational Messages; 12 — Generate through a Chat Completions Provider

**Status:** ready-for-agent

**Type:** implementation

- [ ] Structured-output APIs accept a Pydantic BaseModel subclass or an explicit framework JSON Schema specification.
- [ ] Compilation produces a stable schema name, normalized JSON Schema, strictness metadata, optional qualified type name, and canonical fingerprint.
- [ ] The serialized Run Plan contains the schema snapshot and fingerprint but never the Python class object.
- [ ] Provider-backed Reviewer and Verifier flows receive validated typed results through Chat Completions.
- [ ] Local validation remains mandatory even when the endpoint claims constrained decoding.
- [ ] Refusal, incomplete output, invalid JSON, schema mismatch, and unsupported schema constructs produce distinct typed failures.
- [ ] Nested models, collections, enums, aliases, nullable fields, and forbidden extras are covered by contract tests.
- [ ] Malformed structured output cannot authorize a Message or produce a valid Verification score.
