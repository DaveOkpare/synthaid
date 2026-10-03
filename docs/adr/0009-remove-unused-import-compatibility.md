---
status: accepted
date: 2026-10-02
amends:
  - ADR-0007
  - ADR-0008
---


> [ADR-0010](./0010-use-concrete-agents-and-recorded-episodes.md) replaces the runtime interfaces below with concrete Agent ownership, direct Environment scheduling and recorded Episodes; removed names have no aliases.
# Remove unused import compatibility

The user superseded the earlier blanket API-preservation requirement: unused
modules and components should be removed, including legacy compatibility code.
The provider factory already uses ordinary Chat Completions/Responses transports;
`vllm.py` is referenced only by compatibility tests. Inspection's UI forwards
similarly exist only to preserve old import locations.

Delete `vllm.py`, its `VllmProvider`/`VllmCapabilities` aliases, and inspection's
UI/wildcard forwards. Remove the top-level `InspectionSession` alias. UI callers
import `InspectionSession` and `run_terminal` from `agentinstruct.ui.terminal`.
vLLM callers use the shared HTTP providers and the existing server launcher.

Compatibility alone no longer justifies unused wrappers or exports. Audit
production, CLI, task references, examples, persistence, and public extension
usage before removal; lack of a direct Python caller does not establish that a
task-selected component is unused. Active task fields, native options, saved
Trace reading, local validation, and Review before effects remain supported.

This intentionally retires the old imports without fallback shims. Update
callers and behavior tests to use canonical modules rather than keep code alive
solely to satisfy compatibility tests.
