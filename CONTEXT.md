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
The current implementation follows [ADR-0027](docs/adr/0027-restore-runner-to-the-task-loop.md): Runner opens Episodes and calls Environment; Environment owns execution/finalization. Structural domain protocols and application-owned resources from ADR-0026 remain. [ADR-0025](docs/adr/0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md) retains the SDK and one-Task-per-execution decisions; its constructor/resource design is superseded.

## Generation

**Task**:
A dataclass containing Agents in turn order, input, an optional verifier, one turn limit and its Episode. It creates a fresh Agent copy with an empty history for each participant.
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
Owns output_dir and loops over prepared Tasks. It opens each existing Episode at output_dir / episode.id, invokes Environment.run(task, client=...) and collects that Episode. It accepts a structural Environment instance; the default is a stateless UserSimEnv. It adds no deadline, failure handling, sealing, judgment, preparation or resource-management policy. Environment owns execution/finalization; Episode owns recording invariants. Applications and the optional loader prepare Tasks/evaluators and own clients/resources.
_Avoid_: Workflow engine, orchestrator

**Model Client**:
The application-owned asynchronous client for an inference endpoint, holding network/credential settings. The application initializes it in its async entry point and closes it after the intended batch. Runner.client passes this same borrowed dependency through Environment to Agents. The optional loader constructs model-backed Judges with explicit borrowed clients before execution. Explicit Judge instances retain their declared client. Each call supplies its model and messages; client sharing does not share Conversation or verdict state. Callable-only generation/evaluation can use client=None; model-backed evaluation needs an explicit client. Different endpoints require explicit separate clients. Runtime owners do not close a borrowed client between Tasks. OpenAI SDK 2.30.0 is pinned after offline Agent/Judge parity; Runner.client is implemented.
_Avoid_: Client manager, model instance, Episode

**Agent**:
A participant that calls the OpenAI Responses API and optionally revises its response from reviewer feedback. It owns its private history, including tool activity and review feedback, and declares its model, instruction and Tools. UserSimEnv publishes approved reply text.
_Avoid_: Role, policy

**Evaluator**:
A structural protocol supplying async evaluate(messages) -> Judgment. Domain implementations need no SDK attributes, Judge inheritance or resource fields. Reviewers and verifiers share this interface, while their invoking owners choose the messages and timing. Results are Judgment values with passed, feedback and an optional score.
_Avoid_: Evaluation factory, lifecycle owner

**Provider**:
The inference endpoint accessed through a model client.
_Avoid_: Agent, model, runtime

**Provider API Surface**:
The endpoint's Responses wire protocol.
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
A structural protocol with one method: async run(task, *, client=None) -> None. An implementation owns the Task execution into its opened Episode, including beginning recording, deadline/failure policy, sealing generation and final verification. Runner opens the Episode and invokes this method directly. The default UserSimEnv activates ordered segments and schedules assistant/user Agents. It owns no clients or generic resources. Custom implementations need no framework inheritance, factories, setup, reset or step methods; invocation state stays local and cancellation is cooperative.
_Avoid_: Runtime, sandbox, orchestrator

**UserSimEnv**:
The built-in Environment: Agents speak in turn, only their published replies cross to the other Agent, and an optional verifier evaluates the recorded conversation.
_Avoid_: Lifecycle manager, simulator Agent

**Runtime**:
The place where framework code, agents, and tools execute; local execution is the only v1 runtime.
_Avoid_: Environment

**Observation**:
The latest published reply supplied to an Agent, added to its own private history.
_Avoid_: Context, state

**Action**:
One OpenAI-style message or nonempty ordered sequence of messages proposed by an agent during its interaction turn.
_Avoid_: Turn, response

**Episode**:
The identified history/output created automatically with Task and shared across its segments: accepted Conversation, execution Events and verification results. Its read-only id is UUID-based and exists before execution; its read-only messages view initially contains no accepted messages. Task.episode holds it; Environment and Agents use it. Drafts/review Events remain separate. Episode.open(path) establishes recording without changing identity before accepted appends/Tool effects; construction itself writes no files. It owns history projection, durable recording, segment provenance and task-wide sealed generation. Serialization/format conversion is optional and retains target/visibility rules. Separate Tasks have separate Episodes/history. Verification records append without changing generation, and historical Trace JSON remains readable with recorded IDs intact.
_Avoid_: Agent session, Run

**Message**:
A TypedDict with role and content for text conversation messages; an ordinary OpenAI-format dictionary at runtime.

**Conversation**:
The ordered published replies in the Episode. Tool exchanges remain in the owning Agent’s private history.
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

**Judgment**:
An evaluator's passed verdict, weighted score and optional feedback.

**Judge**:
An evaluator using a model or a check callable to grade each criterion, compute the weighted score, and accept only when score > threshold. It may return feedback.
_Avoid_: Quality-call layer, judge factory

**Reviewer**:
An evaluator invoked by an Agent before returning a response.
_Avoid_: Final verification

**Rubric**:
A list of criteria and an explicit acceptance threshold.
_Avoid_: Reward, score

**Verifier**:
The optional Evaluator supplied as verifier on Task, specifying final judgment of its Episode's sealed accepted history across all executed segments. Environment invokes it once after task-wide generation seals, before run returns. Rejected drafts are excluded. It uses the same constructor/evaluate interface as a Reviewer, with separate invocation timing and results; reverification appends decisions without changing generation. It replaces the proposed episode_judge name.
_Avoid_: Message approval

**Criterion**:
A pass/fail condition described by its context, with a positive weight.
_Avoid_: Metric, reward

Ownership and API retirement: [ADR-0011](docs/adr/0011-remove-plans-and-use-ordinary-task-records.md), [ADR-0012](docs/adr/0012-keep-runner-as-an-environment-task-loop.md), and the implemented [ADR-0014](docs/adr/0014-use-task-lists-and-task-owned-run-settings.md)/[ADR-0015](docs/adr/0015-separate-environment-setup-and-run.md)/[ADR-0016](docs/adr/0016-build-seven-directly-usable-generation-modules.md)/[ADR-0017](docs/adr/0017-use-agent-reviewers-task-verifiers-and-independent-episodes.md)/[ADR-0018](docs/adr/0018-runner-owns-the-output-directory.md)/[ADR-0019](docs/adr/0019-task-owned-episodes-span-segments.md)/[ADR-0020](docs/adr/0020-create-an-identified-episode-with-each-task.md)/[ADR-0021](docs/adr/0021-declare-tools-on-each-agent.md)/[ADR-0022](docs/adr/0022-construct-agent-definitions-and-revise-from-review.md)/[ADR-0023](docs/adr/0023-use-agent-directly-and-keep-execution-state-local.md)/[ADR-0024](docs/adr/0024-use-required-assistant-and-optional-user-task-roles.md). ADR-0013's active Taskset design is superseded. Saved run_plan fields are ordinary historical JSON metadata, not runtime Plans.

Current execution ownership is defined by [ADR-0027](docs/adr/0027-restore-runner-to-the-task-loop.md), restoring the Runner/Environment responsibility split from ADR-0012 and the library specification. ADR-0026's structural protocols remain; its Runner-owned lifecycle is superseded.
