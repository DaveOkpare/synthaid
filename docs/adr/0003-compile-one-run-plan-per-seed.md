---
status: accepted
date: 2026-09-23
amends:
  - ADR-0001
  - ADR-0002
---

# Compile one immutable run plan per seed

> Amended by [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md), which replaces atomic `TurnCommit` bundles with incremental `MessageCommit` records and makes each terminal trace a complete export source. [ADR-0005](./0005-use-an-openai-shaped-provider-protocol-with-vllm-conformance.md) adds the compiled Provider boundary and capability preflight.

ADR-0001 defines one seed as producing one trace, but its glossary calls the per-seed execution a run while its persistence layout places multiple traces beneath one run identifier. That ambiguity makes it unclear whether a CLI invocation processes one seed or an entire seed source, whether task steps create separate conversations, and what has been validated when execution begins.

We will use `Run` for one invocation of a task over a configured seed source. A run contains zero or more per-seed traces. The compiler creates one immutable `RunPlan` for each valid seed, and executing that plan produces exactly one trace. A trace retains one accepted conversation across all of its task steps.

This ADR amends ADR-0001's run cardinality and persistence terminology. It refines the `Task` argument in ADR-0002's environment protocol to a compiled `TaskContext` and adds the optional `finalize` hook. ADR-0002's environment and interaction-turn decisions otherwise remain unchanged.

## Decision

### One invocation consumes the selected seed source

The configured seed path may identify a file or directory:

```toml
[seed]
path = "seeds/"
glob = "*.jsonl"
id_variable = "case_id"

[variables]
case_id = "case.id"
user_goal = "scenario.goal"
```

The built-in seed source supports the following cardinality:

- A JSONL line is one seed.
- A CSV row is one seed.
- A JSON array element is one seed.
- A JSON object is one seed.
- A directory contributes records from files matching its required `glob`, ordered first by path and then by record position.

The framework does not generate seeds. It reads the configured source or a Python iterable supplied by a library caller. Format parsing, optional JSON Schema validation, dot-path variable extraction, and strict template rendering happen before model execution for each seed.

`id_variable` names a task-wide variable declared in `[variables]`; it is not a second dot path. Seed identifiers must be unique within a run. When no identifier variable is configured, the framework derives the seed ID from a canonical content hash.

V1 processes seeds sequentially. A seed-specific invalid or failed trace does not prevent later seeds from running by default. The CLI may expose `--fail-fast` for callers that prefer to stop at the first such outcome.

### Runs, seeds, traces, steps, and turns have distinct identities

The identity hierarchy is:

```text
Run                               one task invocation over a seed source
└── Trace                         one execution attempt for one seed
    ├── Task Step                 one instruction phase in that trace
    └── TurnCommit                one atomically accepted interaction turn
```

The corresponding identifiers have these meanings:

- `run_id` identifies the collection-level invocation.
- `seed_id` identifies the logical source record and is stable when the same record is reused.
- `trace_id` identifies one execution attempt for one seed. Rerunning a seed creates a new trace ID while retaining its seed ID.
- `step_id` identifies the active task step that contributed instructions and rubrics to a turn.
- `turn_id` identifies one accepted bundle of tool and participant messages.

`run_id` and `trace_id` are generated identities rather than content identities. Digests are recorded separately for the task package, seed, run plan, and relevant component definitions.

### `TaskPackage` is unresolved authoring input

`TaskPackage` is loaded once from the task directory:

```python
@dataclass(frozen=True)
class TaskPackage:
    root: Path
    config: TaskConfig
    seed_source: SeedSourceSpec
    agents: Mapping[AgentId, AgentSource]
    steps: tuple[StepSource, ...]
    verifier: VerifierSource | None
    content_digest: str
```

It owns the parsed `task.toml`, conventional instruction and rubric files, declared component references, seed-source specification, and package content digest. Its instructions are still templates. It contains no extracted seed variables, rendered instructions, live model clients, conversation state, or provider credentials.

Loading and preparing a package validates the schema version, safe paths, file layout, unique identifiers, ordered step declarations, exactly one target agent, referenced tools and components, and configuration that does not depend on a particular seed.

### `Seed` preserves source data and provenance

One record from the seed source becomes:

```python
@dataclass(frozen=True)
class Seed:
    id: str
    data: Mapping[str, JsonValue]
    origin: SeedOrigin
    digest: str
```

`data` preserves the original JSON-compatible value. `origin` records its source path and record position, such as a JSONL line, CSV row, or JSON array index. Dot paths traverse nested mappings in JSON-compatible seeds. CSV records are flat unless a custom seed loader explicitly produces nested values.

Variable aliases are not copied into or defined by `Seed`; the compiler derives them from the task's `[variables]` mapping. This keeps the external record distinct from the task-specific interpretation of that record.

### `RunPlan` is the immutable per-seed execution input

After binding a prepared task package to one seed, the compiler emits:

```python
@dataclass(frozen=True)
class RunPlan:
    schema_version: str
    task: TaskIdentity
    seed: Seed
    variables: Mapping[str, JsonValue]
    agents: Mapping[AgentId, AgentPlan]
    steps: tuple[StepPlan, ...]
    tools: Mapping[ToolId, ToolPlan]
    environment: EnvironmentPlan
    verifier: VerifierPlan | None
    runtime: RuntimePlan
    provenance: PlanProvenance
    digest: str
```

The plan contains resolved defaults, validated component references, extracted variables, rendered instructions, appended rubric definitions, tool assignments, the ordered steps, environment configuration, final-verifier configuration, and secret-scrubbed provenance. It contains no live agents, environment instance, recorder, conversation, model responses, or verification result.

An agent plan contains the persistent participant configuration:

```python
@dataclass(frozen=True)
class AgentPlan:
    id: str
    target: bool
    model: ModelPlan
    base_instruction: str
    tool_ids: tuple[ToolId, ...]
    reviewer: ReviewerPlan | None
    base_rubric: tuple[RubricCriterion, ...]
```

A step plan contains only the temporary additions for that phase:

```python
@dataclass(frozen=True)
class StepPlan:
    id: str
    agents: Mapping[AgentId, StepAgentPlan]


@dataclass(frozen=True)
class StepAgentPlan:
    instruction: str
    appended_rubric: tuple[RubricCriterion, ...]
```

For an active step, the effective instruction is the rendered base instruction plus the rendered current-step instruction. The effective reviewer rubric is the base rubric plus the current-step rubric. A step transition removes only the previous step's temporary contribution; it never removes accepted history.

### The runner owns execution after compilation

The collection-level API is conceptually:

```python
package = TaskPackage.load(path)
result = await Runner().run(package)
```

The framework performs the following lifecycle:

```text
load and statically validate TaskPackage
  -> open Run record
  -> enumerate seeds deterministically
  -> for each seed:
       parse and validate Seed
       -> extract variables and render templates
       -> compile immutable RunPlan
       -> open per-seed Trace record
       -> resolve and preflight components
       -> create fresh trace-bound agents, tools, reviewers, and environment
       -> Environment.setup(...)
       -> Environment.run(task_context, agents)
            -> activate task step
            -> Interaction.turn(...)
                 -> project accepted history for the participant
                 -> generate drafts and execute private tools
                 -> review and revise
                 -> atomically commit the accepted turn
                 -> return the accepted reply reference
       -> Environment.finalize(...)
       -> seal an immutable generation trace
       -> Verifier.verify(trace_snapshot)
       -> validate criterion verdicts and derive the weighted score
       -> persist accepted, rejected, unverified, or failed status
       -> add the trace reference to the run index
  -> finalize the Run manifest and summary
```

Component construction happens after compilation so invalid configuration, variables, templates, and capabilities fail before model spend. Every trace receives fresh trace-bound agent and interaction state. A stateful provider client may be pooled internally, but no accepted conversation or reviewer state may leak between traces.

### Environments receive a narrow compiled task view

An environment does not receive the entire `RunPlan`. It receives an immutable `TaskContext` projection containing only the task identity, seed identity and variables, ordered task steps, termination configuration, and the operations needed to activate a step:

```python
class Environment(Protocol):
    async def setup(self, agents: Agents) -> None: ...

    async def run(
        self,
        task: TaskContext,
        agents: Agents,
    ) -> None: ...

    async def finalize(
        self,
        task: TaskContext,
        trace: TraceSnapshot,
    ) -> None: ...
```

`finalize` is optional and defaults to a no-op. The runner wraps all three hooks with timeout, error capture, cleanup, and persistence. The environment cannot access provider credentials, persistence internals, or final-verifier configuration through `TaskContext`.

### One trace owns one conversation across all task steps

`conversation.jsonl` belongs to the trace, not to a task step. Each record is a `TurnCommit` containing the ordered accepted message bundle from one interaction turn and its `step_id`.

Accepted participant messages persist across every step. Accepted tool calls and results are stored in canonical order but are projected only to the invoking participant. Drafts, critiques, rejected revisions, raw model calls, lifecycle transitions, and failures remain in `events.jsonl` and never enter accepted model-visible history.

The persistence layout is:

```text
runs/<run-id>/
  source-task/                     # immutable task-package snapshot
  manifest.json                    # versions, hashes, status, timing, counts
  traces.jsonl                     # append-only trace index
  traces/<trace-id>/
    run-plan.json                  # rendered, secret-scrubbed per-seed plan
    trace.json                     # seed identity, status, provenance, references
    conversation.jsonl            # accepted TurnCommit records across all steps
    events.jsonl                  # drafts, reviews, calls, failures, lifecycle
    verification/<attempt-id>.json
    artifacts/
```

Persisting the rendered plan per trace is necessary because two seeds render different instructions even when they use the same task package. The source task is snapshotted once at the run root to avoid duplicating its authoring files for every seed.

### Failures are scoped to the narrowest recoverable boundary

- A task-package or seed-source failure prevents the run from starting or continuing because the framework cannot identify executable work reliably.
- Once a source record has a stable origin, a seed validation, variable extraction, or rendering failure is indexed as an `invalid` trace with no accepted conversation.
- Agent, tool, reviewer, environment, runtime, or persistence failure marks that trace `failed`; any durable partial conversation and events remain inspectable.
- A final-verifier execution or result-validation failure marks the generated trace `unverified` without mutating its conversation.
- A valid verifier result marks the trace `accepted` or `rejected` according to its weighted threshold.

The runner continues to the next seed unless fail-fast behavior was explicitly requested. Reverification appends another verification attempt to an existing immutable trace and does not regenerate the conversation.

The returned collection result is:

```python
@dataclass(frozen=True)
class RunResult:
    run_id: str
    traces: tuple[TraceRef, ...]
    counts: RunCounts
```

`RunCounts` distinguishes accepted, rejected, unverified, invalid, and failed traces rather than collapsing them into a single success flag.

## Considered Options

- **Run only one seed per CLI invocation.** Rejected because seed collections are the ordinary data-generation unit and would force users to build orchestration and aggregation outside the library.
- **Use `Run` for one seed and introduce a separate job or batch abstraction.** Rejected for v1 because the user-visible command naturally represents one task invocation and already owns a directory containing multiple traces. A separate public batch object adds terminology without adding behavior.
- **Compile one monolithic plan containing every rendered seed.** Rejected because large seed sources should be streamed, invalid records should remain isolated, and rendering all seeds before execution would increase memory use and startup latency.
- **Create one conversation file per task step.** Rejected because steps reveal temporary instructions within one continuing interaction. Splitting the files would make retained history and cross-step ordering harder to inspect and replay.
- **Pass the complete `RunPlan` to environments.** Rejected because it exposes provider, verifier, runtime, and persistence details that environment authors do not need and could accidentally depend on.
- **Reuse live agents across seeds.** Rejected because mutable provider, interaction, reviewer, or tool state could leak between generated examples and compromise reproducibility.

## Consequences

- A single `run` command processes every record in its configured file, directory, or supplied iterable and produces one indexed trace per seed attempt.
- Task packages are parsed once, while seed-dependent validation and rendering remain isolated per trace.
- Every model call starts from a fully validated immutable plan, making failures earlier and provenance clearer.
- Conversation history remains continuous across task steps and can be replayed without reconstructing ordering from separate files.
- Environment implementations remain small because the runner owns collection iteration and lifecycle while `Interaction.turn()` owns draft acceptance.
- Per-trace plans consume additional storage, but they make the exact rendered input reproducible and inspectable.
- V1 intentionally favors deterministic sequential processing; parallel seed execution can be added later without changing the package, plan, trace, or environment contracts.

## References

- [ADR-0001](./0001-data-generation-first-agent-trace-architecture.md)
- [ADR-0002](./0002-use-run-based-dialogue-environments.md)
- [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md)
- [ADR-0005](./0005-use-an-openai-shaped-provider-protocol-with-vllm-conformance.md)
- [Prime and Harbor module research](../../research/prime-harbor-module-patterns.md)
