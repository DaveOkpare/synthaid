# Agent Trace Generation

This context describes a Python library for generating reviewed synthetic data from agent interactions through seven deep modules: Task, Runner, Environment, Agent, Episode, Tools and Judge.

The implemented ownership below follows [ADR-0014](docs/adr/0014-use-task-lists-and-task-owned-run-settings.md)
and [ADR-0015](docs/adr/0015-separate-environment-setup-and-run.md), with module consolidation and direct imports in [ADR-0016](docs/adr/0016-build-seven-directly-usable-generation-modules.md), Agent reviewers in [ADR-0017](docs/adr/0017-use-agent-reviewers-task-verifiers-and-independent-episodes.md), Runner-owned output in [ADR-0018](docs/adr/0018-runner-owns-the-output-directory.md), Task-owned Episodes across segments in [ADR-0019](docs/adr/0019-task-owned-episodes-span-segments.md), automatic Episode creation in [ADR-0020](docs/adr/0020-create-an-identified-episode-with-each-task.md) and Agent-owned Tool declarations in [ADR-0021](docs/adr/0021-declare-tools-on-each-agent.md).
[ADR-0022](docs/adr/0022-construct-agent-definitions-and-revise-from-review.md)
specifies revision from reviewer guidance;
[ADR-0023](docs/adr/0023-use-agent-directly-and-keep-execution-state-local.md)
uses Agent directly and removes the separate definition/runtime representation.
[ADR-0024](docs/adr/0024-use-required-assistant-and-optional-user-task-roles.md)
keeps Task.agents with a required assistant target and optional user Agent.
The seven-module implementation is complete. [ADR-0025](docs/adr/0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves constructor-bound Environment(task).run(), one Task per execution,
and adoption of the pinned SDK with application-owned clients.

## Generation

**Task**:
An inert execution definition containing public input, configured Agent instances (each with its own Tools and optional reviewer), ordered segments, an optional verifier and execution limits. Task.agents holds the definitions directly: assistant is required and always the target; user is optional and may be omitted. Those are the only permitted keys, and declared values must be Agent instances. There are no separate Task.assistant/Task.user fields or configurable target flag. Task has no tools field or shared Tool pool. Construction automatically creates its own empty Episode with a unique ID; task.episode and task.episode.id are immediately available. The first execution uses that same Episode/ID, shared across all segments. Episode is not a required configuration argument. Construction performs no file writes, model/Tool calls or live resource acquisition. Task has no separate message_judge or episode_judge field. Applications prepare Tasks; Environment validates and uses their Agents, declared Tools/reviewers and optional verifier. Only public input and active instructions are available to Agents; grading-only data and future segment instructions remain private.
_Avoid_: Benchmark, evaluation

**Taskset**:
Simply a list of Tasks. Each Task carries configured Agents with their own Tools/reviewers, segments and its optional verifier. Taskset has no loading, verification or resource-lifetime behavior.
_Avoid_: Task Package, Dataset, Plan

**Task Package**:
The optional authoring directory containing `task.toml`, instruction and rubric templates, component declarations, and a seed-source specification. A plain loader prepares Tasks; it is not a required runtime owner or core import.
_Avoid_: Run configuration, executable task

**Seed**:
One external input record used to prepare a Task and its Episode, potentially spanning several segments. A seed's storage format and creation process remain outside the framework.
_Avoid_: Example, test case

**Variable**:
A unique task-wide name bound to a validated dot-path within every seed and available to strict instruction templates.
_Avoid_: Parameter, field mapping

**Run**:
One Task execution, potentially containing multiple segments sharing its Episode. Runner.run is a batch loop returning those Episodes. The repeat policy uses a new Task from the same definitions for another independent sample, preserving earlier outputs. Historical task-file run manifests/IDs may identify a batch; they remain saved adapter metadata rather than a required core Run owner.
_Avoid_: Episode, trial, batch

**Trace**:
The persisted representation of one Episode: accepted conversation, execution events, provenance, artifacts and verification results.
_Avoid_: Transcript, trajectory

**Dataset**:
A collection exported from traces according to acceptance and inclusion rules.
_Avoid_: Run collection

## Participants and execution

**Runner**:
Owns output_dir and uses output_dir / task.episode.id to open recording for the Episode already created with Task. It does not replace that Episode or its ID before execution. It accepts Tasks, an injected client and an optional Environment class, constructs Environment(task) once per Task and collects Task.episode after run. Applications or the optional authoring adapter prepare Tasks; participant assembly, segment/conversation execution and invocation of Task.verifier belong to Environment; recording at the selected path belongs to Episode.
_Avoid_: Workflow engine, orchestrator

**Model Client**:
The application-owned asynchronous client for an inference endpoint, holding network/credential settings. The application initializes it in its async entry point and closes it after the intended batch. Runner.client passes this same borrowed dependency through Environment to Agents and Judges translated from ordinary settings. Explicit Judge instances retain their declared client. Each call supplies its model and messages; client sharing does not share Conversation or verdict state. Callable-only generation/evaluation can use client=None; model-backed evaluation needs an explicit client. Different endpoints require explicit separate clients. Runtime owners do not close a borrowed client between Tasks. OpenAI SDK 2.30.0 is pinned after offline Agent/Judge parity; Runner.client is implemented.
_Avoid_: Client manager, model instance, Episode

**Agent**:
A directly constructed participant: Agent(model, instruction, tools=(), reviewer=None), with revision settings such as max_revisions=1. Task.agents holds these objects and Environment uses them directly. Only that Agent's declared Tools are advertised or callable; shared capability references must be explicitly declared on each Agent. turn(episode) calls generate(history), applies its reviewer/revision policy, records accepted output and executes approved private Tools. For revision, generate receives temporary private history containing the rejected draft and reviewer guidance, and Agent authors a replacement for another review. generate is the customization seam; it does not authorize effects or accept output. Agent keeps stable settings; Episode owns accepted/private history and continuation state, while drafts/feedback/counters stay local to each turn. The same built-in Agent can serve separate Episodes concurrently without state leakage. Environment passes client, participant identity and active instructions per invocation rather than rebinding Agent. Custom Agents obey the same state rule or callers provide separate instances for mutable dependencies. Construction is inert and snapshots Tool collections.
_Avoid_: Role, policy

**Provider**:
The model-client dependency used for inference through its selected Responses or Chat Completions API. The core has no public Provider request/response hierarchy. Agent uses an injected client or a custom generate override; Judge uses an injected client or a callable check. SDK/transport types stay implementation details.
_Avoid_: Agent, model, runtime

**Provider API Surface**:
The wire protocol selected by an actual Provider: `responses` or `chat_completions`, recorded in Trace evidence.
_Avoid_: Provider type, model API

**Structured Output Schema**:
A framework-owned output contract normalized from a `Pydantic.BaseModel` class or JSON Schema, sent through a Provider API Surface and validated locally after generation.
_Avoid_: Response model, provider schema

**Target Agent**:
The required assistant entry in Task.agents, whose behavior the generated data is intended to train or distill. Target selection follows that role without a separate Boolean flag; the user Agent cannot be the target or signal Task completion.
_Avoid_: Solver

**Simulator**:
The optional user Agent that interacts with the assistant target to create the scenario. It occupies the user entry in Task.agents, rather than introducing another participant type.
_Avoid_: Opponent

**User Agent**:
The optional user entry in Task.agents, acting as the simulated counterparty to the assistant. Omitting it gives assistant-only execution. Domain identities such as patient, customer, or learner belong in its instructions. It can have its own Tools/reviewer and a custom generation implementation; accepted messages remain context rather than the training target.
_Avoid_: Human user

**Assistant Agent**:
The required assistant entry in Task.agents and always the target Agent. assistant is the default participant role; an actual configured Agent must still be supplied. Its domain identity belongs in its instructions, and it may have its own Tools/reviewer or custom generation implementation. There is no separate AssistantAgent subclass or target setting.
_Avoid_: Clinician, support agent

**Segment**:
An ordered phase within a Task, represented as ordinary data with a name and Agent-specific instruction additions. Instruction keys can address only the assistant or a configured user; segments cannot introduce participants or change the target. Environment activates segments in order without replacing Task.episode or its accepted history. Only the current segment's instruction additions are active; base instructions remain. Segment completion uses ordinary conversation policy/limits, without built-in advancement Tools or a progress-owner class.
_Avoid_: Task, environment step, Plan

**Task Step**:
The historical task-file term for a segment. The optional adapter keeps authored phases within one Task as segments; it does not expand them into independent Tasks.
_Avoid_: Turn, environment step

**Environment**:
A usable implementation taking Task and injected execution dependencies. The implemented interface is Environment(task, client=...) plus async run() -> None, replacing the earlier public setup call. Its constructor performs local validation/participant assembly; any async preparation belongs inside run's cleanup scope. run executes all segments into the Task's existing Episode, seals task-wide generation once and supplies accepted history to the verifier. It does not allocate or return an Episode. Environment has no output_dir constructor argument and releases execution resources on success, failure or cancellation. Shared infrastructure can be injected; participant definitions and verifier settings come from Task. Concurrent executions use separate Task and Environment instances. There are no reset or step methods.
_Avoid_: Runtime, sandbox, orchestrator

**Runtime**:
The place where framework code, agents, and tools execute; local execution is the only v1 runtime.
_Avoid_: Environment

**Observation**:
The model-visible OpenAI-style message history projected for one agent, including only accepted conversation content and that agent's private tool exchanges.
_Avoid_: Context, state

**Action**:
One OpenAI-style message or ordered list of messages proposed by an agent during its interaction turn.
_Avoid_: Turn, response

**Episode**:
The identified history/output created automatically with Task and shared across its segments: accepted Conversation, execution Events and verification results. Its read-only id is UUID-based and exists before execution; its read-only messages view initially contains no accepted messages. Task.episode holds it; Environment and Agents use it. Drafts/review Events remain separate. Episode.open(path) establishes recording without changing identity before accepted appends/Tool effects; construction itself writes no files. It owns history projection, durable recording, segment provenance and task-wide sealed generation. Serialization/format conversion is optional and retains target/visibility rules. Separate Tasks have separate Episodes/history. Verification records append without changing generation, and historical Trace JSON remains readable with recorded IDs intact.
_Avoid_: Agent session, Run

**Conversation**:
The canonical ordered history of accepted participant messages and accepted tool calls and results.
_Avoid_: Event log, transcript

**Message Commit**:
The atomic durable append of one accepted OpenAI-style message. Tool-call, tool-result, and conversational messages commit separately while retaining their shared turn and step references.
_Avoid_: Turn bundle, event

**Event**:
A non-conversational record of execution, such as a draft, critique, revision, model call, error, or lifecycle transition.
_Avoid_: Message

**Tool**:
An agent-invocable capability with a declared identifier, description, JSON input schema, and asynchronous call contract. An Agent definition's tools collection determines availability for that Agent; Tool calls resolve through that assignment. Task has no tools field or global Tool lookup. The optional file loader resolves authoring catalogs into explicit per-Agent definitions without changing this ownership.
_Avoid_: Environment action

## Quality

**Judge**:
The directly usable evaluator with one constructor for both message review and final Episode evaluation. Model evaluation uses client/model/prompt and an optional Rubric; callable evaluation uses check and an optional Rubric. Agent.reviewer and Task.verifier accept the same Judge class, and an instance can serve both roles when its criteria fit. evaluate(messages) returns a validated judgment with verdict/criteria and text feedback. Message review receives the invoking Agent's accepted visible context plus its unaccepted proposal; final verification receives sealed accepted Episode history. Judge keeps no mutable conversation, Episode binding, revision counters or accumulated verdicts. Per-call state is local; Agent owns revisions/acceptance, and Episode records invocation evidence/results. Borrowed clients remain application-owned. Ordinary authored settings translate into this same class without role subclasses or binding wrappers.
_Avoid_: Quality-call layer, judge factory

**Reviewer**:
The optional Judge supplied as reviewer on an Agent definition. It evaluates that Agent's proposals, including Tool calls, before acceptance/effects. A rejection provides actionable guidance or suggested edits; Agent uses the review and rejected draft to generate a replacement and reviews it again before acceptance. Reviewer does not rewrite accepted output. Different Agents can use different Judge configurations or None; appropriately configured instances can be shared without revision-state leakage. Revision limits belong to Agent. Drafts/review guidance remain private Events, excluded from peer history/default export. Reviewer is an invocation role of Judge, without a task-wide message_judge or separate required module/constructor.
_Avoid_: Final verification

**Rubric**:
The named weighted Boolean criteria and threshold configured with an Agent's Reviewer or Task's final Verifier; file-declared phase criteria can append to base criteria before execution.
_Avoid_: Reward, score

**Verifier**:
The optional Judge supplied as verifier on Task, specifying final judgment of its Episode's sealed accepted history across all executed segments. Environment invokes it once after task-wide generation ends, before run returns. Rejected drafts are excluded. It uses the same constructor/evaluate interface as a Reviewer, with separate invocation timing and results; reverification appends decisions without changing generation. It replaces the proposed episode_judge name.
_Avoid_: Message approval

**Criterion**:
A uniquely identified Boolean quality condition with a weight used to derive a normalized reviewer or verifier score.
_Avoid_: Metric, reward

Ownership and API retirement: [ADR-0011](docs/adr/0011-remove-plans-and-use-ordinary-task-records.md), [ADR-0012](docs/adr/0012-keep-runner-as-an-environment-task-loop.md), and the implemented [ADR-0014](docs/adr/0014-use-task-lists-and-task-owned-run-settings.md)/[ADR-0015](docs/adr/0015-separate-environment-setup-and-run.md)/[ADR-0016](docs/adr/0016-build-seven-directly-usable-generation-modules.md)/[ADR-0017](docs/adr/0017-use-agent-reviewers-task-verifiers-and-independent-episodes.md)/[ADR-0018](docs/adr/0018-runner-owns-the-output-directory.md)/[ADR-0019](docs/adr/0019-task-owned-episodes-span-segments.md)/[ADR-0020](docs/adr/0020-create-an-identified-episode-with-each-task.md)/[ADR-0021](docs/adr/0021-declare-tools-on-each-agent.md)/[ADR-0022](docs/adr/0022-construct-agent-definitions-and-revise-from-review.md)/[ADR-0023](docs/adr/0023-use-agent-directly-and-keep-execution-state-local.md)/[ADR-0024](docs/adr/0024-use-required-assistant-and-optional-user-task-roles.md). ADR-0013's active Taskset design is superseded. Saved run_plan fields are ordinary historical JSON metadata, not runtime Plans.
