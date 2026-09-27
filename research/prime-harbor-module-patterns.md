# Prime Intellect and Harbor module patterns

Research date: 2026-09-23. Primary sources only. Prime Intellect Verifiers was inspected at commit [`0b46c8c`](https://github.com/PrimeIntellect-ai/verifiers/tree/0b46c8c22ebada6c45b34391be7d55d39f1a2006). Harbor was inspected at commit [`15da91c`](https://github.com/harbor-framework/harbor/tree/15da91c18580a25489f5bdf2ee71029f3ff3bb2e).

This report evaluates reusable patterns against [ADR-0002](../docs/adr/0002-use-run-based-dialogue-environments.md) and [CONTEXT.md](../CONTEXT.md). It does not propose making either upstream project's object model our own.

## Executive recommendation

Use **Prime Intellect's execution core** and **Harbor's task-package and operational shell**.

- Prime has the better live-generation boundary: an `Environment` defines ordinary Python control flow, an `Agent` opens an `Interaction`, and `Interaction.turn()` performs one strict caller-driven exchange. The framework base class owns lifecycle, error capture, resource cleanup, and trace completion around that user-authored control flow.
- Harbor has the better package boundary: a task is a validated directory, conventional paths make it inspectable, multi-step structure is explicit, unsafe paths are rejected, resolved configuration is locked, trials preserve partial results, and completed outputs can be reverified without rerunning the agent.
- Our framework must keep its own data-generation semantics: one trace per seed; one canonical accepted multi-party conversation; participant-private tool and execution records; pre-acceptance draft review; strict template variables; and post-run weighted boolean verification. Neither Prime nor Harbor provides that combination.

The existing ADR made the correct central choice: keep `Environment.run(task, agents)` and make `Interaction.turn()` the accepted-turn boundary. The main missing pieces are a pure compile/validation phase, a framework-owned run lifecycle, a root trace with private participant subrecords, durable turn commits, typed failure semantics, and shallow component discovery.

## The combined architecture

The recommended boundaries are:

| Module | Owns | Must not own |
|---|---|---|
| `TaskPackage` | Reading `task.toml`, conventional files, path validation, schema version | Seed generation, model calls |
| `Compiler` | Seed loading, dot-path extraction, strict template rendering, rubric/config validation, immutable `RunPlan` | I/O side effects beyond reading inputs |
| `Runner` | Run lifecycle, timeouts, errors, cleanup, final verification dispatch, status | Dialogue policy |
| `Environment` | Who interacts when, task-step activation, termination/truncation | Provider calls, review implementation, persistence internals |
| `Agent` | Run-bound participant facade and interaction creation | Cross-agent scheduling |
| `Interaction` | Observation projection, generation, private tool loop, review/revision, accepted-turn commit | Overall dialogue flow |
| `Tool` | Declared capability and one actor-aware call | Scheduling or transcript mutation |
| `Reviewer` | Pre-acceptance boolean rubric verdicts and critiques for a draft | Final dataset eligibility |
| `RunRecorder` | Atomic accepted-turn commits, append-only events, artifacts, provenance | Deciding what is accepted |
| `Verifier` | Post-run criterion verdicts over an immutable trace snapshot | Mutating generation history |
| `RunStore` | Run directories, manifests, indexes, atomic finalization, reverify outputs | Generation control flow |
| `Registry` | Built-in short IDs and explicit custom entrypoints | Package-hub policy or implicit fallback |

This preserves the vocabulary already established in `CONTEXT.md`: `Environment` is interaction control flow, while `Runtime` is where execution happens. In v1 the only runtime is `local`.

## Recommended lifecycle

```text
TaskPackage.load(path)
  -> validate schema, paths, layout, target cardinality
  -> load one seed
  -> validate dot-path variables
  -> sandbox and render every base/step instruction
  -> compile immutable RunPlan
  -> open durable Run record
  -> create fresh run-bound Agents
  -> Environment.setup(...)
  -> Environment.run(task, agents)
       -> activate task step
       -> Interaction.turn(incoming)
            -> project accepted history for this participant
            -> generate draft and private tool activity
            -> review; revise until passing or the revision cap is exhausted
            -> atomically commit the passing or marked fallback message bundle
            -> return accepted typed reply/reference
       -> relay accepted replies in ordinary Python
  -> Environment.finalize(...)
  -> close generation trace as completed, truncated, or failed
  -> Verifier.verify(immutable_trace)
  -> validate complete boolean verdict set
  -> derive weighted score and threshold acceptance
  -> finalize run manifest and index
```

Framework-owned lifecycle code should wrap environment hooks. Prime's base `Env` does this well: `setup`, `run`, and `finalize` are extension points, while `run_episode()` creates fresh agents, applies timeouts, captures failures, and finalizes the episode ([environment lifecycle](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/env.py#L147-L184), [run orchestration](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/env.py#L242-L305)). Harbor likewise places preparation, cleanup, exception capture, output recovery, and result persistence in its trial base rather than in each workload implementation ([trial lifecycle](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/trial/trial.py#L447-L526)).

For v1, add optional `finalize()` to the public environment protocol. `start()` and `stop()` are useful collection-level hooks for shared resources, but may stay internal until there is a runtime or tool that needs them. Prime's `complete()` resume policy should be deferred until resume exists.

## Pattern decisions

### Adopt

| Pattern | Source | Why it belongs here |
|---|---|---|
| `Environment.run(task, agents)` as the authoring surface | Prime documents environments as complete agent-control-flow programs and provides single-agent, user-simulation, judge, and sampling variants ([docs](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/docs/v1/env.md#L1-L21)). | It is a small deep interface and matches ADR-0002. Custom environments remain ordinary Python rather than configuration graphs. |
| Strict interaction state and resource ownership | Prime permits one turn at a time, validates who may speak first, rejects turns after closure, and uses an async context to guarantee cleanup ([`Interaction` and `Segment`](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/agent.py#L143-L259)). | It prevents ambiguous first turns, concurrent mutation, and leaked sessions. |
| Fresh run-bound agents | Prime constructs fresh agent instances for every episode while sharing only explicitly shared resources ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/env.py#L192-L240)). | Mutable model/tool/session state cannot leak between seeds. |
| Conventional, validated task packages | Harbor loads a task directory through `TaskPaths`, validates required task and test inputs, and distinguishes root instruction from ordered steps ([task loading](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/models/task/task.py#L32-L86), [validation](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/models/task/task.py#L95-L189)). | Files remain understandable without framework code; invalid jobs fail before model spend. |
| Safe path resolution and portable step names | Harbor rejects traversal/cycles and validates output symlinks; step names are checked for portable characters and normalized collisions ([path safety](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/utils/path_safety.py#L5-L30), [step names](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/models/task/step_name.py#L4-L30)). | Task packages are untrusted input and eventually may run in non-local runtimes. |
| Sandboxed, strict instruction rendering | Harbor uses Jinja's `SandboxedEnvironment` with `StrictUndefined`, inspects undeclared variables, and rejects missing or unknown simulator variables ([templating](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/utils/templating.py#L7-L17), [variable validation](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/utils/templating.py#L53-L98)). | This directly supports the selected seed-variable design. Parse and render all instructions before opening any model session. |
| Capability declaration and preflight | Harbor agents and execution environments expose capabilities and factories reject unsupported combinations before a run ([agent factory](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/agents/factory.py#L38-L139), [environment factory](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/environments/factory.py#L21-L198)). Prime harnesses likewise declare support for tools, images, and other features ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/harness.py#L34-L55)). | A compiled run should fail clearly if a backend cannot satisfy its task. |
| Typed errors at framework boundaries | Prime explicitly lets extension code raise normal exceptions, classifies them once at framework boundaries, and stores rollout failure as data rather than crashing unrelated work ([error design](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/errors.py#L1-L89)). | Partial traces remain useful and users can distinguish invalid input, failed generation, failed verification, and threshold rejection. |
| Complete, duplicate-free rubric verdict validation | Prime requires unique criteria, finite nonnegative weights, a positive total weight, and a complete set of allowed verdicts with no duplicates or unknowns ([criterion validation](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/judges/rubric.py#L60-L110), [verdict validation](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/judges/rubric.py#L146-L183)). | A malformed judge response is a verifier error, never an implicit failed criterion. |
| Resolved provenance plus source snapshot | Prime writes both launch TOML and fully resolved JSON configuration before appending complete episodes ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/cli/output.py#L93-L191)). Harbor lock models preserve resolved task, agent, verifier, and environment configuration ([source](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/models/job/lock.py#L175-L288)). | Every trace needs reproducible inputs, selected implementations, hashes, and runtime/model provenance. |
| Reverification without regeneration | Harbor's regrade flow reruns the verifier against copied prior outputs without rerunning the agent ([docs](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/docs-mintlify/core-concepts/jobs/regrade.mdx#L1-L9)). | Verification evolves independently from expensive trace generation. A `reverify` operation should append a new versioned verification result. |

### Adapt

| Pattern | Upstream behavior | Adaptation for data generation |
|---|---|---|
| Prime `UserSimEnv` relay loop | It opens user and assistant interactions, hides the scenario from the assistant, relays replies, and stops on a marker ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/envs/user_sim/env.py#L38-L99)). | Keep the tiny relay loop, generic seats, and view separation. The configured initiator sends the first message. Relay a typed accepted message/reference, not only text; structured termination replaces a magic marker as the canonical contract. |
| Prime `Segment` | A segment contains every assistant message and intervening tool result, a root reply, and termination state ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/agent.py#L143-L168)). | Return an accepted `TurnResult`: ordered accepted messages, accepted outbound reply, termination/truncation reason, and review-exhaustion state. Rejected or failed attempts are events and are never returned as accepted output. |
| Prime `Episode` plus per-agent `Trace` | An episode groups one independently recorded trace per participating agent ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/episode.py#L87-L105)). | Keep one root `Trace` per seed, with one canonical accepted conversation and nested participant records for private observations, tool calls, drafts, model calls, and errors. This satisfies both shared ordering and participant privacy. |
| Prime trace provenance | Traces capture resolved agent identity, task identity, model-call sampling, usage, timing, finish reason, errors, tools, and scores ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/trace.py#L86-L177), [trace schema](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/trace.py#L399-L456)). | Record the same operational provenance, plus reviewer attempts and accepted-message references. Keep the native trace participant-aware; ATIF can be an export format later. |
| Prime harness boundary | An agent is composed from a model, harness, runtime policy, and task tools ([agent](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/agent.py#L262-L317)). | Internally introduce an `AgentBackend`/`Driver` so `Agent` is not permanently coupled to one provider loop. Keep it out of task vocabulary unless multiple backends require user choice. |
| Tools and toolsets | Prime registers decorated methods as named MCP tools, supports per-rollout state, and distinguishes task-scoped from shared toolsets ([toolset](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/mcp/toolset.py#L16-L34), [stateful server](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/mcp/server.py#L131-L247)). | Keep the selected small `Tool.call(arguments, context)` protocol. Record tool schema/version/hash and isolate state per run. Commit tool calls/results only with an accepted turn and show them only in the invoking participant's observation. |
| Weighted judge output | Prime stores per-criterion metrics and a weighted aggregate ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/judges/rubric.py#L243-L272)). Harbor's verifier returns numeric reward mappings ([protocol](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/verifier/base.py#L14-L43)). | Canonical verifier output remains `criterion_id -> bool`. The framework, not the implementation, computes `sum(weight for true) / sum(weight)` and compares it to the task threshold. Record LLM judge request, response, usage, cost, parse failure, and criterion outputs independently. |
| Isolated verification | Prime can evaluate in a fresh runtime containing declared artifacts, and Harbor can run a verifier in a separate environment with transferred artifacts ([Prime](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/envs/isolated_verifier/env.py#L60-L182), [Harbor](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/docs-mintlify/core-concepts/tasks/separate-verifier.mdx#L6-L16)). | Adopt the semantic boundary now: verifier input is an immutable trace snapshot and declared artifacts, and output commits only after validation. Defer actual container isolation while the only runtime is local. |
| Persistence | Prime appends one whole episode to JSONL; Harbor stores structured trial directories with logs, artifacts, results, and step outputs ([Prime](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/cli/output.py#L1-L9), [Harbor paths](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/models/trial/paths.py#L84-L146)). | Use one inspectable directory per trace plus an append-only run index. Persist each accepted turn before it is relayed; write a `TurnCommit` atomically so a tool-call/result/outbound-message bundle cannot be half accepted. Final verification is a separately versioned file. |
| Discovery | Prime resolves built-in IDs and installed plugins with strict errors; Harbor accepts built-ins or explicit `module.path:ClassName` imports ([Prime](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/utils/loaders.py#L70-L126), [Harbor](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/utils/import_path.py#L6-L42)). | Provide short IDs for built-ins and `package.module:object` for custom implementations. Load lazily, validate the protocol immediately, and never silently fall back after an explicit lookup fails. |
| Taskset/seed loading | Prime's `Taskset` is lazy and offers deterministic views and shuffling ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/taskset.py#L38-L110)). | Keep seed creation out of scope. The v1 runner accepts the configured JSON/JSONL/CSV path or a Python iterable, yields one validated seed at a time, and produces one trace per seed. Add shuffle/sampling only as runner conveniences later. |
| CLI affordances | Harbor provides task scaffolding, component listing/schema inspection, run commands, and trace export ([CLI registration](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/cli/main.py#L133-L189), [task init](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/cli/init.py#L73-L166)). | Keep a thin CLI: `init`, `validate`, `run`, `inspect`, `export`, and `reverify`. `inspect` is the simple TUI already selected. Component `list`/`schema` can follow when third-party components exist. |

### Reject or defer

| Pattern | Decision | Rationale |
|---|---|---|
| Separate participant traces as the only canonical record | **Reject** | Reconstruction can produce ambiguous ordering and duplicates. The dataset primitive is one accepted multi-party conversation, with participant-private execution as linked subrecords. |
| Fresh conversation for every Harbor task step | **Reject** | Harbor starts a fresh conversation for each step by default and optionally resumes state ([multi-step docs](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/docs-mintlify/core-concepts/tasks/multi-step.mdx#L139-L165)). Our task steps reveal fresh phase instructions while accepted history is always retained. |
| Per-step verifier/reward checkpoints | **Reject** | Harbor verifies each multi-step phase and may stop on a reward threshold ([source](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/trial/multi_step.py#L100-L147), [early stop](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/trial/multi_step.py#L195-L242)). Our step rubrics feed the participant reviewer; the trace verifier runs once after generation ends. |
| Mapping Prime `Segment` to Task Step | **Reject** | A Prime segment is one resumed agent exchange, not a phase that activates new instructions and criteria. Keep `TurnResult` and `Task Step` separate. |
| Harbor simulated-user bridge as the core model | **Reject** | Harbor gives its user agent a chat tool and lets it control the conversation; the target receives no task instruction ([RFC](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/rfcs/0002-simulated-users.md#L62-L74)). It also disallows a user agent in multi-step trials ([source](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/trial/multi_step.py#L24-L39)). Independent participants coordinated by an environment are more general. |
| Magic completion marker | **Reject as protocol** | Prime's user simulator uses `###DONE###`. A marker may be a convenience in one built-in simulator, but canonical termination needs a structured reason. |
| Reward as the primary artifact | **Reject** | A scalar loses criterion-level supervision and cannot distinguish a failed verifier from a negative verdict. Score and acceptance are derived from strict boolean results. |
| ATIF as canonical persistence | **Reject for v1; export later** | Harbor's ATIF RFC is agent-centered and models a root agent trajectory rather than one native multi-party accepted conversation ([RFC](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/rfcs/0001-trajectory-format.md#L90-L140)). Stable message IDs and provenance should make a later exporter possible. |
| Message DAG and token-level masks/logprobs | **Defer** | Prime's DAG efficiently supports branching, compaction, and subagents ([design](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/graph.py#L1-L18)). A linear accepted conversation plus stable message IDs is sufficient for v1. Keep `parent_id`/references extensible. |
| Automatic agent or whole-run retries | **Reject for v1** | Retries change provenance and cost. Preserve explicit revision attempts inside reviewers, persist failures, and add user-requested reruns later with distinct attempt IDs. |
| Parallelism, routing, best-of-N, agentic judge environments | **Defer** | Prime demonstrates these as environment variants, including concurrent best-of-N sampling. The selected v1 only needs single-agent generation and back-and-forth multi-party simulation. Custom Python environments remain the escape hatch. |
| MCP/shared/remote tool servers | **Defer** | The direct Tool protocol and local runtime cover v1. MCP or ORS should later be adapters rather than internal contracts. |
| Container/remote runtimes and isolated verifier execution | **Defer** | The architecture should expose capability and immutable-input boundaries now, but `local` is the chosen v1 default and only required implementation. |
| Plugin hubs, implicit package scanning, auth/jobs/sweeps | **Defer** | They expand operations and compatibility surface before the core trace contract is stable. An explicit registry plus import path is enough. |

## Task packages and multi-step behavior

Harbor's filesystem convention is the right inspiration, but its evaluation semantics are not. Its task configuration defines ordered, uniquely named steps with per-step agent/verifier overrides ([configuration](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/src/harbor/models/task/config.py#L760-L842)); its docs make the step directory order explicit ([docs](https://github.com/harbor-framework/harbor/blob/15da91c18580a25489f5bdf2ee71029f3ff3bb2e/docs-mintlify/core-concepts/tasks/multi-step.mdx#L10-L67)). Adapt that shape to the already selected participant-first instruction structure:

```text
task.toml
seeds.jsonl
agents/
  user/
    instruction.md
    rubric.toml            # optional, base reviewer criteria
  assistant/
    instruction.md
    rubric.toml
steps/                     # absent for a single-step task
  intake/
    agents/
      user/instruction.md
      assistant/instruction.md
      assistant/rubric.toml
  resolution/
    agents/
      user/instruction.md
      assistant/instruction.md
verifier/
  rubric.toml              # optional when final verification is disabled
```

For a single-step task, use `agents/<agent-id>/instruction.md` without `steps/`. Base agent rubrics and current-step agent rubrics append. Variables are task-wide and globally unique; they do not belong under a step or agent. Step activation replaces only the previous step instruction/rubric contribution while preserving base instructions, all accepted conversation messages, and that participant's private accepted tool history.

The runner should expose one internal activation operation—conceptually `agents.activate_step(step)`—that updates every participant atomically and emits `step_started`. Environment authors should not recreate or close interactions merely because a task phase changed.

## Trace and persistence shape

Prime's provenance depth and Harbor's inspectable directory layout combine well if the root record follows our data model:

```text
runs/<run-id>/
  source-task/                    # immutable task snapshot or content-addressed reference
  resolved-task.json             # rendered, secret-scrubbed RunPlan
  manifest.json                  # versions, hashes, components, status, timings, errors
  traces.jsonl                   # append-only collection index
  traces/<trace-id>/
    trace.json                   # identities, seed reference, status, message/event refs
    conversation.jsonl           # atomic accepted TurnCommit records
    events.jsonl                 # drafts, critiques, revisions, calls, failures, lifecycle
    verification/<attempt-id>.json
    artifacts/
```

A `TurnCommit` contains the ordered accepted message bundle produced by one interaction turn. This lets the recorder durably append tool calls, tool results, and the final outbound participant message as one acceptance unit before the environment relays the reply. Projection rules then give every participant the accepted participant messages but only the invoking participant its private tool messages. As already selected in ADR-0001, exhausting the configured revision cap commits the last draft as an explicit `review_exhausted` fallback; the final verifier may still reject the trace. If the turn fails before either a passing draft or that configured fallback, no `TurnCommit` is written and all attempts remain in `events.jsonl`.

Every message, event, model call, tool call, verification attempt, and artifact should have a stable ID. This is enough for joins and future DAG export without imposing a graph store in v1.

Recommended status distinctions:

- `invalid`: configuration, seed, variable, template, or capability validation failed before the run;
- `completed`: environment reached a legitimate end;
- `truncated`: a limit, timeout, or execution failure ended generation early;
- `unverified`: generation is durable but verification failed or produced malformed output;
- `accepted` / `rejected`: derived only after successful verification and threshold comparison.

Use boundary-specific recorded failures such as `ConfigurationError`, `SeedError`, `TemplateError`, `ProviderError`, `AgentError`, `ToolError`, `ReviewerError`, `EnvironmentExecutionError`, `RuntimeExecutionError`, `VerifierError`, and `PersistenceError`. Each record should include lifecycle stage, participant, task step, draft/revision attempt, timestamp, and chained cause where available.

## Extensibility and public API

The public surface should remain narrow:

```python
class Environment(Protocol):
    async def setup(self, agents: Agents) -> None: ...
    async def run(self, task: Task, agents: Agents) -> None: ...
    async def finalize(self, task: Task, trace: Trace) -> None: ...

class Interaction(Protocol):
    async def turn(self, incoming: MessageRef | Message | None = None) -> TurnResult: ...

class Tool(Protocol):
    async def call(self, arguments: dict, context: ToolContext) -> ToolResult: ...

class Reviewer(Protocol):
    async def review(self, draft: Draft, context: ReviewContext) -> ReviewResult: ...

class Verifier(Protocol):
    async def verify(self, context: VerificationContext) -> VerificationResult: ...
```

`Interaction.turn()` remains the deep facade. Internally it can delegate to an agent backend, tool loop, reviewer loop, and recorder transaction. Environments receive only run-bound `Agent` facades; they should not receive provider clients or a raw recorder, which would let them bypass review and accepted-history invariants.

For discovery, prefer:

```toml
[environment]
type = "dialogue"                    # built-in short ID

[verifier]
type = "my_package.verifiers:Check"  # explicit custom object
```

The loader should lazily import, validate the expected protocol/class, and report the exact failing entrypoint. Do not copy Prime's requirement that a plugin package export exactly one subclass through `__all__`; do not copy Harbor's larger registry/hub surface until distribution requires it.

## Implications for ADR-0002 and `CONTEXT.md`

No existing core decision needs reversal. A future ADR revision should make these points explicit:

1. The framework runner, not the custom environment, owns lifecycle, timeout, cleanup, failure capture, and verifier dispatch.
2. Add optional `Environment.finalize()`; reserve collection-level `start()`/`stop()` hooks for shared resources.
3. Define `TurnResult` as accepted typed messages plus reply/reference, termination/truncation, and review-exhaustion—not a string segment.
4. Define one root `Trace` with a canonical accepted conversation and participant-private execution records.
5. Specify prepare/review/atomic-commit behavior and require durability before relay.
6. Separate Prime's interaction `Segment` from our phase-level `Task Step`.
7. Add a pure task/seed compilation phase and capability preflight before model execution.
8. Version and record reviewer/verifier requests, responses, usage, errors, and results independently from participant calls.
9. Make reverification append-only and independent of generation.
10. Keep automatic retries, distributed runtimes, routing, background events, parallel sampling, and registry infrastructure out of v1.

The one vocabulary addition worth considering is an internal **Agent Backend** (or **Driver**) for the model/harness/provider implementation behind an `Agent`. It should remain implementation terminology unless users actually need to configure multiple backends. `Episode`, `Trial`, `Harness`, `Reward`, and Prime's `Segment` should not enter the public domain model.

## Bottom line

The framework should feel like Harbor when users author, validate, inspect, persist, and reverify a task, and like Prime when environment authors orchestrate agents. Its differentiator is neither task packaging nor a user-simulator loop by itself. It is the accepted-data boundary:

```text
seed-bound instructions
  -> agent draft and private tools
  -> reviewer-controlled revision
  -> atomic accepted multi-party history
  -> durable native trace
  -> independent boolean verification
  -> dataset acceptance/export
```

That boundary is the part to own rather than inherit.
