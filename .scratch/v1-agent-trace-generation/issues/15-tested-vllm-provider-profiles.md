# 15: Add tested vLLM Provider profiles

**What to build:** Let operators configure an external vLLM server as a first-class tested Provider profile for documented structured-output, reasoning, and Tool-calling workflows.

**Blocked by:** 14 — Add Responses API parity and private reasoning

**Status:** ready-for-agent

**Type:** implementation

- [ ] vLLM remains an external OpenAI-compatible service and is not a mandatory core Python dependency.
- [ ] The vLLM profile defaults conservatively to Chat Completions and allows Responses only when that surface is explicitly declared conformant.
- [ ] Typed vLLM options cover the supported current structured-output modes and reasoning controls without an unrestricted extra-body escape hatch.
- [ ] Server flags, parser names, chat template, model revision, vLLM version, API Surface, request profile, and hardware class are recorded as conformance provenance.
- [ ] Deterministic contract tests cover text, Pydantic-backed structured output, reasoning separation, automatic function Tool calls, Tool-result continuation, and typed failures.
- [ ] An opt-in real-server suite exercises every feature combination claimed by the pinned profile.
- [ ] Chat Completions conformance does not imply Responses conformance, and unsupported combinations fail preflight or with a typed endpoint contradiction.
- [ ] The project makes no compatibility claim for a vLLM profile until its recorded real-server suite passes.
