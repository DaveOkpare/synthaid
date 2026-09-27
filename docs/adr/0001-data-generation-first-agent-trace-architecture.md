---
status: superseded by ADR-0002
date: 2026-09-23
---

# Adopt a data-generation-first architecture for verified agent traces

> Superseded by [ADR-0002](./0002-use-run-based-dialogue-environments.md), which replaces the public AEC workflow and domain-specific dialogue naming. [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md) further amends the review, persistence, and export decisions retained from this record. [ADR-0005](./0005-use-an-openai-shaped-provider-protocol-with-vllm-conformance.md) defines the Provider boundary behind Agents.

We will build an open-source Python library with a thin CLI for producing training and distillation data from single-agent and multi-party interactions. The library will borrow Harbor's task packaging and multi-step instruction model, use a Gym/PettingZoo-inspired Agent Environment Cycle (AEC) for execution, and keep pre-acceptance review distinct from post-run verification. This makes generated, replayable traces the primary product rather than treating them as a side effect of evaluation.

The first workload is a patient–clinician dialogue dataset: the clinician is the sole target agent and the patient is a simulator. The core remains domain-neutral so the same primitives can support other synthetic or seed-derived generation workloads.

## Decision

### Task packages are declarative and filesystem-backed

Every task has a `task.toml` and Harbor-style instruction files. `task.toml` declares the schema version, seed defaults, global variables, environment, local runtime, agents, model/provider defaults, tool assignments, ordered task steps, and review limits. Exactly one agent must have `target = true`.

Single-step tasks use only base agent instructions. Multi-step tasks add role-specific instructions beneath global steps:

```text
task/
├── task.toml
├── agents/
│   └── <agent-id>/
│       ├── instruction.md
│       ├── reviewer.md          # optional
│       └── rubric.toml          # optional base review criteria
├── steps/                       # omitted for single-step tasks
│   └── <step-id>/
│       └── agents/
│           └── <agent-id>/
│               ├── instruction.md
│               └── rubric.toml  # optional criteria appended for this step
├── environment/
│   └── environment.py           # only for a custom environment
├── tools/
│   └── tools.py                 # optional custom tools
└── verifier/
    ├── verifier.toml
    ├── judge.md                 # for an LLM verifier
    └── verifier.py              # for a code verifier
```

There are no separate `agent.toml` or `step.toml` files. All agents participate in every declared task step. An agent's base instruction remains active throughout a run; only the current step's instruction is added. Previous step instructions expire, but the full accepted conversation is retained.

### Seeds bind data to strict instruction templates

The framework accepts a default seed path from `task.toml`, a CLI override, or a Python iterable. It does not prescribe how users create seeds. JSON may contain one object or an array of objects, JSONL must contain one object per line, and CSV is flat and addresses exact unique headers.

The task declares unique global aliases in `[variables]`, each mapped to a dot path such as `patient.demographics.age`. Dot-path traversal is validated against every seed before generation, as is optional JSON Schema validation. Jinja renders instructions in strict mode, so missing values fail before a run starts. A configured seed identifier references one of these aliases; otherwise the framework derives an identifier from a content hash. One seed produces one trace in v1.

### A Runner drives an AEC-style Environment

`Environment` means the stateful interaction protocol, not where code executes. `Runtime` means the execution location and is `local` in v1.

The canonical environment boundary is:

```python
class Environment(Protocol):
    @property
    def current_agent(self) -> str: ...

    async def reset(self, seed: Seed) -> tuple[list[Message], dict]: ...
    def observe(self, agent_id: str) -> list[Message]: ...
    async def step(self, action: Message | list[Message]) -> StepResult: ...
    async def close(self) -> None: ...
```

The runner reads `current_agent`, asks that agent to act on its observation, applies its reviewer when enabled, and submits only the accepted action to `step`. The environment owns state transitions, participant selection, task-step progression, termination, and truncation; it does not invoke models. `step` does not need an `agent_id` because the environment already exposes the only valid actor.

The library ships two environments:

- `single`, containing exactly one target agent;
- `dialogue`, containing exactly two agents and one target, with a configurable initiator that only determines who sends the opening message, followed by automatic back-and-forth interaction.

A dialogue limit counts full back-and-forth rounds. Multi-party protocols beyond two participants use the same public protocol through a custom environment; routing graphs, parallel execution, and a general turn-policy abstraction are not part of v1.

Task-step completion and run completion are reserved environment actions available only to the target agent. They are represented as reserved tool-call message sequences so the resulting history remains structurally valid. Maximum-round limits protect every run. A legitimate completion sets `terminated`; exhausted limits, provider/tool failures, or other incomplete endings set `truncated`.

The async API is canonical, with a synchronous wrapper for ordinary scripts. Seed processing is sequential in v1.

### OpenAI-style messages form one accepted conversation

`Message` follows the OpenAI message shape: role, content, name, tool calls, and tool-call identifier, extended with an `actor_id` so the native format can represent peers. An action is one message or an ordered list of messages, allowing a normal assistant/tool-call/tool-result/assistant sequence.

The trace has one canonical conversation ordered exactly as interaction occurred. It contains only accepted participant messages and accepted tool calls/results. Tool exchanges are stored centrally but appear only in the invoking agent's observations; another participant receives only the accepted conversational consequence. Each agent sees its base instruction, current task-step instruction, the accepted history projected into its perspective, and its own tool exchanges.

Drafts, reviewer feedback, revisions, rejected actions, model calls, errors, and lifecycle transitions are stored in a separate event stream and are never silently inserted into model-visible history.

### Review happens before acceptance; verification happens after the trace

Review is an explicit per-agent option. A reviewer uses stable instructions from `reviewer.md`, the agent's base `rubric.toml`, and any step-specific criteria appended for the current task step. Criterion identifiers must remain unique after composition. The reviewer may use the owning agent's provider/model defaults or explicit overrides, and `max_revisions` is configurable.

For each draft, the reviewer returns a complete mapping of criterion identifiers to booleans plus feedback. All criteria passing accepts the draft. Otherwise the agent revises within the same `step()` cycle. When the revision cap is reached, the last draft is accepted and marked `review_exhausted`; the review attempts stay in events rather than conversation history.

After recording the complete trace, one final verifier evaluates it. LLM judges and deterministic Python verifiers implement the same protocol and return exactly one boolean for every declared criterion. Missing, duplicate, unknown, or malformed results are verifier errors rather than failed criteria. Each criterion has a weight; the framework derives a normalized score by awarding the weight for `true` and zero for `false`, then marks the trace accepted when that score meets the configured threshold.

Every raw run is persisted. A successfully scored trace is `accepted` or `rejected`; verifier execution failure makes it `unverified`, allowing later re-verification without regenerating the interaction.

### Native traces preserve generation provenance

The canonical format is participant-aware rather than ATIF because ATIF's root model is a single agent trajectory and cannot faithfully express one shared peer conversation, private per-agent tool visibility, review events, and typed verifier outcomes without project-specific conventions.

Each run is stored as:

```text
runs/<run-id>/
├── manifest.json
├── conversation.jsonl
├── events.jsonl
├── verification.json
└── artifacts/
```

The manifest records task and seed identity/hashes, the full seed by default, resolved variables, provider/model and inference settings, reviewer configuration, environment/runtime/tool identities, package and Python versions, timestamps, and the termination reason. Invalid tasks, seeds, or templates fail before creating a run; execution failures retain a partial truncated run. Automatic retries are not part of v1.

### Public entry points stay small

The Python interface centers on `Task.load(...)`, `Runner(...).run(seed)`, asynchronous `generate(task, seeds)`, and `generate_sync(...)`. Built-in OpenAI and OpenAI-compatible agents are included; callers may supply custom objects implementing the agent protocol.

Tools follow one framework protocol with an identifier, description, JSON input schema, and asynchronous `call(arguments, context)` method. Function and agent-wrapped tool adapters are included in v1. Tools are declared task-wide and assigned per agent for all task steps.

The CLI exposes `validate`, `run`, `inspect`, and `export`. Inspection has a static summary and an optional simple TUI for conversation, reviewer events, verification, and provenance. Export supports the native format and OpenAI JSONL, selects accepted traces by default, and can explicitly include rejected traces or review events.

## Considered Options

- **Copy Harbor as an evaluation framework.** Rejected because the primary artifact here is reusable generated data. Harbor's task packaging and step layout remain useful, while its evaluation-first lifecycle does not define the multi-party generation loop we need.
- **Use a tabular synthetic-data pipeline like NeMo Data Designer.** Rejected as the core abstraction because it does not make stateful agent interaction, private tools, draft review, or accepted conversational history first-class.
- **Let an environment call both agents internally.** Rejected for the public protocol. It is convenient, and Prime Intellect Verifiers demonstrates the pattern, but it conflates policy/model execution with environment transition. The AEC split allows custom agents and environments to compose independently while a deep `Runner` hides the loop for common use.
- **Declare turn order or workflow graphs in the task.** Rejected for v1. Built-in dialogue needs only an initiator and automatic alternation; novel schedules belong in custom environment code until repeated use cases justify another abstraction.
- **Use rewards during generation.** Rejected. Review produces accept/revise decisions before a message enters history, while final verification produces named booleans and a derived score after generation. This keeps quality evidence interpretable and re-runnable.
- **Use ATIF as the canonical trace.** Deferred to a future export adapter because its single-agent root does not match the shared multi-party record.

## Consequences

- The framework has three intentionally separate extension points: agents propose actions, environments govern interaction, and verifiers judge completed traces.
- A trace is reproducible and auditable because accepted conversation, internal events, verification, and provenance are recorded separately.
- Patient–clinician simulation can stress the abstractions without introducing healthcare-specific core types.
- The narrow built-ins leave remote or sandboxed runtimes, concurrent/vectorized seeds, background or scheduled messages, more-than-two-party built-ins, MCP/ORS adapters, ATIF export, hosted services, and automatic retries outside v1.
- The first implementation must validate task structure, dot paths, Jinja variables, criterion identity, and verifier completeness before optimizing throughput.

## References

- [Harbor core concepts](https://docs.harborframework.com/core-concepts) and [multi-step tasks](https://docs.harborframework.com/core-concepts/tasks/multi-step)
- [PettingZoo Agent Environment Cycle](https://pettingzoo.farama.org/api/aec/)
- [OpenEnv](https://github.com/huggingface/OpenEnv)
- [Open Reward Standard](https://openrewardstandard.io/)
- [Prime Intellect Verifiers environment model](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/docs/v1/env.md)
- [Harbor Agent Trajectory Interchange Format RFC](https://github.com/harbor-framework/harbor/blob/main/rfcs/0001-trajectory-format.md)
- [Local environment and verification research](../../research/environment-verifier-landscape.md)
