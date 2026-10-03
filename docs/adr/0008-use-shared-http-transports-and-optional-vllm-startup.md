---
status: accepted
date: 2026-10-01
amends:
  - ADR-0005
  - ADR-0006
  - ADR-0007
---

# Use shared HTTP transports and optional vLLM startup

> Amended by [ADR-0009](./0009-remove-unused-import-compatibility.md): the unused legacy provider wrapper and inspection import bridges are retired.

The user reviewed the vLLM isolation checkpoint and rejected maintaining a
separate adapter and server-certification subsystem. A vLLM OpenAI-compatible
server should be used through its base URL like any other compatible endpoint.
The user explicitly authorized deleting the integration provider/conformance
modules and packaging a short startup command.

## Decision

- Keep one HTTP implementation per API: Chat Completions and Responses. Provider
  selection includes OpenAI, compatible endpoints, and legacy `type = "vllm"`.
  A vLLM task needs a base URL and model; its default API remains Chat Completions.
- Keep legacy generation names, typed options, and task profile fields readable.
  `VllmProvider` is a small wrapper selecting the shared implementation. Native
  options are translated at its common wire boundary with local validation.
  Legacy profiles are provenance metadata rather than execution gates.
- Remove conformance modules, synthetic lookup/answer cases, the certification
  sample profile, and the conformance CLI. Certification-only imports/commands
  are deliberately retired; report digests are no longer required to connect.
  Existing data model fields stay readable for saved Plan/Trace compatibility.
- Place optional startup in `integrations/vllm/serve.py`, exposed lazily through
  `agentinstruct vllm --model MODEL -- PROGRAM ...`. It starts the official serve
  entrypoint in a child process, waits for readiness, runs the supplied program,
  and cleans up owned processes. The server interpreter owns the vLLM dependency.
  The launcher uses POSIX process groups and runs from the main thread.
- Retain explicit API selection, local structured-result validation, private
  reasoning, safe error evidence, no automatic retries/fallbacks, and Review
  before Tool effects. Server/model support is expressed by ordinary request
  responses, without an embedded certification workflow.

This supersedes ADR-0005/0006's mandatory profiles and conformance gates and
ADR-0007's promise to preserve conformance entry points. Agent-owned Review and
Runner-owned final Verification remain separate and unchanged by this slice.

## Consequences

There is one client transport path to maintain. Old generation Tasks and saved
Traces remain readable. Profiles no longer certify model capabilities; offline
tests verify client behavior without making live server compatibility claims.
The shipped launcher adds process lifecycle code but imports no inference engine.
