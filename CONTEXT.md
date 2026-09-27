# Agent Trace Generation

This context describes a domain-neutral framework for generating verified traces from agent interactions.

## Generation

**Task**:
A versioned recipe that binds agents, instructions, seed variables, an environment, tools, review policy, and final verification into a reproducible generation job.
_Avoid_: Benchmark, evaluation

**Task Package**:
The unresolved authoring directory containing `task.toml`, instruction and rubric templates, component declarations, and a seed-source specification.
_Avoid_: Run configuration, executable task

**Seed**:
One external input record used to produce exactly one trace. A seed's storage format and creation process remain outside the framework.
_Avoid_: Example, test case

**Variable**:
A unique task-wide name bound to a validated dot-path within every seed and available to strict instruction templates.
_Avoid_: Parameter, field mapping

**Run**:
One invocation of a task over a configured seed source, containing zero or more independently recorded traces.
_Avoid_: Episode, trial, batch

**Run Plan**:
The immutable, validated, rendered, and secret-scrubbed execution specification produced for one seed before any model call.
_Avoid_: Task package, conversation state

**Trace**:
The durable record of one seed execution attempt within a run: its accepted conversation, internal events, provenance, artifacts, and verification result.
_Avoid_: Transcript, trajectory

**Dataset**:
A collection exported from traces according to acceptance and inclusion rules.
_Avoid_: Run collection

## Interaction

**Agent Specification**:
The task-owned definition of a participant, including its identity, instructions, model defaults, tools, review policy, and whether it is the target.
_Avoid_: Agent configuration

**Agent**:
A runtime participant that turns an observation into an action.
_Avoid_: Role, policy

**Provider**:
An asynchronous adapter that translates framework-owned model requests and responses to one inference service while declaring its supported capabilities.
_Avoid_: Agent, model, runtime

**Provider API Surface**:
The wire protocol selected for a Provider Plan, initially `responses` or `chat_completions`. It is compiled into the Run Plan and recorded in Trace provenance.
_Avoid_: Provider type, model API

**Structured Output Schema**:
A framework-owned output contract normalized from a `Pydantic.BaseModel` class or JSON Schema, sent through a Provider API Surface and validated locally after generation.
_Avoid_: Response model, provider schema

**Target Agent**:
The single participant whose behavior the generated data is intended to train or distill.
_Avoid_: Solver

**Simulator**:
A non-target participant that interacts with the target agent to create the scenario.
_Avoid_: Opponent

**User Agent**:
The generic simulated-counterparty role in the built-in dialogue environment. Domain identities such as patient, customer, or learner belong in its instructions.
_Avoid_: Human user

**Assistant Agent**:
The generic responding role in the built-in dialogue environment and the usual target in user-simulation tasks. Its domain identity belongs in its instructions, and the task still marks the target explicitly.
_Avoid_: Clinician, support agent

**Task Step**:
An ordered phase that temporarily adds role-specific instructions and review criteria while retaining the accepted conversation from earlier phases.
_Avoid_: Turn, environment step

**Environment**:
The stateful control flow that opens agent interactions, relays accepted replies, advances task steps, and determines termination or truncation.
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

**Interaction**:
A trace-bound session for one agent whose `turn()` operation handles generation, private tools, review, and persistence of accepted output.
_Avoid_: Environment step

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
An agent-invocable capability with a declared identifier, description, JSON input schema, and asynchronous call contract.
_Avoid_: Environment action

## Quality

**Reviewer**:
An optional per-agent pre-acceptance loop that scores each model-produced message, including a tool-call message, against the active rubric before the message enters accepted history or causes an effect.
_Avoid_: Verifier, judge

**Rubric**:
The named weighted Boolean criteria and threshold used by a reviewer for one agent; active step criteria append to the agent's base criteria.
_Avoid_: Reward, score

**Verifier**:
A post-run implementation that evaluates the completed trace against declared weighted criteria, independently of generation.
_Avoid_: Reviewer

**Criterion**:
A uniquely identified Boolean quality condition with a weight used to derive a normalized reviewer or verifier score.
_Avoid_: Metric, reward
