# Migrate to the seven generation modules

This is a deliberate Python API change. Removed interfaces have no aliases.
Runner writes the lean Episode as plain JSON. Historical trace loading is retired.

| Former API or ownership | Replacement |
| --- | --- |
| Runner(environment, task dictionaries) | Runner(list[Task], output_dir=..., client=..., environment=domain_instance) |
| Environment.setup(task), run(task), conversation(episode), async context ownership | Environment is a protocol: async run(task, *, client=None); Runner assigns its trace path and invokes an implementation instance; UserSimEnv records messages and optionally verifies |
| Environment allocates/returns Episode; environment.output_dir | Task creates episode immediately; Runner assigns output_dir / episode.id / trace.json; Environment.run returns None; Runner saves and collects the Episode |
| Separate Agent definition/runtime or AgentObservation | Construct Agent directly; supply custom sampling with generator=domain_object |
| Agent.turn(episode) and single-sample Agent.generate | Agent.generate(history, *, client=None, role="assistant") returns a reviewed proposal; UserSimEnv records accepted conversation messages |
| Arbitrary participant names, Agent.id/target, separate assistant/user fields | Task.agents with required assistant and optional user; role is invocation-local |
| Task-level tools or global Tool lookup | Agent.tools: explicit sequence of Tool objects, default empty |
| FunctionTool and Tool subclasses with contexts | Tool(async_function, id=..., description=..., input_schema=...); custom factories return Tool |
| Provider, ProviderRequest/Response, ChatCompletionsProvider, ResponsesProvider | Application-owned AsyncOpenAI; Agent supports Chat Completions only; Judge retains its API selection |
| Reviewer/Verifier classes and request/result factories | Judge(check=...) or Judge(client=..., model=..., prompt=..., rubric=...) |
| Taskset or global message_judge / episode_judge | list[Task]; Agent.reviewer and Task.verifier |
| Root Criterion/Rubric/ReviewResult exports | Criterion, Rubric, Judgment from agentinstruct.judge |
| Root Message/FunctionCall/ToolCall exports | Supporting values from agentinstruct.episode |
| LocalRunStore, RecordedTrace, TraceSnapshot, load_trace | Data-only Episode dataclass; Runner writes traces; plain JSON reads and optional Inspector |
| TaskPackage, Seed, component registries, generate/generate_sync | adapters.task_files.compile_records/load_tasks; Runner.run or asyncio.run in the application |
| Built-in steps, Tool execution and Task deadlines | Steps and Task deadlines are removed; custom Environments can execute Tools |
| Plans, lifecycle/control Tools, reset/step methods | Ordinary Task input and one UserSimEnv.run conversation loop |
| Structured-output subsystem | Tool parameter schemas for model calls and Judge Rubric checks |

Agent construction is inert. A custom generator must keep execution
state local or in the supplied Episode/history; externally mutable dependencies
need explicit application ownership. The same configured Agent or Judge can serve
independent concurrent Tasks. Runner creates each Task's output directory
exclusively; reusing that output fails before generation. Episode itself is
ordinary mutable trace data.

Clients are borrowed through Runner/Environment/Agent and Judge. Explicit Agent and
Judge clients retain their declared dependency. Initialize and close each endpoint's
client in the application's outer async scope. Configure SDK retries explicitly;
core model calls force max_retries=0.

Task files preserve assistant/user syntax, templates, source formats, Tool catalogs,
review rubrics. Target flags are allowed only when consistent with those
fixed roles. Other roles and custom scheduling references produce migration errors;
use direct structural Environments for custom scheduling. Custom generation references
must name plain Generator classes with no-argument constructors; custom Judge references name
message-check callables; custom Tool references name factories returning Tool.
Compilation validates these references syntactically without importing them.

Deterministic task-file checks evaluate accepted Messages: nonempty_content,
nonempty_conversation, assistant_present, and user_present. The former
`generation_terminated` check depended on a Trace wrapper and is rejected explicitly.
Applications apply completion policies around execution; Episode no longer
classifies generation outcomes. Shipped structural-check examples use
assistant_present. This does not establish semantic correctness or full completion.

## Task holds conversation data

Task has five fields: agents, input, verifier, max_turns and an automatically created
episode. Its only method checks the participant keys and positive turn limit.
Supplied mappings remain ordinary data without copies or frozen wrappers.

Remove Task.roles and initiator. Agent dictionary order determines turn order;
use {"user": user, "assistant": assistant} for user-first dialogue. Task still
requires assistant and permits an optional user. Use max_turns for the total message
limit, defaulting to 20. Replace max_rounds with the corresponding message count.

Task.segments, timeout_seconds, provenance and declaration are removed. Task files
reject steps and the removed scheduling settings. Put extra trace metadata directly
in Episode.metadata; the task-file adapter puts seed provenance there. UserSimEnv
adds Task input under the input key. Automatic Agent/Judge configuration snapshots
and their declaration helpers are removed. Applications can use asyncio.timeout.

## Tools define a schema and call a function

Tool has four fields: function, id, description and input_schema. The id defaults
to the function name. `schema()` returns the Chat Completions function declaration;
Agent uses it for model requests.
`call(arguments)` awaits the function with the supplied mapping and returns its
result unchanged. Function errors and cancellation propagate directly.

ToolError, schema_validator, validate, validate_result, declaration, output_schema
and execution_errors are removed. Put any required validation or error handling
in the function itself. Tool does not copy arguments, validate JSON or convert
results. Task files reject the removed output_schema and execution_errors options.
Seed schemas still use jsonschema directly in the task-file adapter.

## Episode records data only

Episode now has five public dataclass fields: id, messages, metadata, verification
and path. It has no methods. Messages are an ordinary list and
verification is a Judgment or None. No properties or lifecycle flags are required.

UserSimEnv appends accepted messages, calls the optional verifier directly and
stores its result in memory. Runner chooses the recording path and saves once per
Task, including when execution raises or is cancelled. Standalone Environments
work in memory; use Runner for disk persistence.

Each save writes a temporary JSON file, flushes it and replaces the destination
atomically. A failed write raises the underlying error and leaves traces from
earlier Tasks intact. Abrupt process termination can lose the current Task's
unsaved messages. Completed snapshots and partial snapshots have the same data shape;
verification=None does not by itself signal completion.

Remove calls to open, begin, append, history, seal, record, verify, load, export, save,
to_dict and training_messages. Use messages.append, direct evaluator calls,
Runner and ordinary JSON reads instead. Episode no longer stores events, status,
generation classifications or verification histories. Live clients are not stored;
message and feedback text are saved as supplied, without automatic redaction.
Unused Message fields for evidence, reasoning, visibility, segments and timestamps
are also removed.

The saved JSON keys are id, messages, metadata and verification. Old trace formats,
ledger files, sidecars, historical verification selection and CLI reverification
are retired. The optional Inspector and CLI export read the current snapshot shape.

The shared json_data, canonical_json, parse_json and freeze helpers are removed.
Callers use standard json.dumps/json.loads and dataclasses.asdict. Task input,
argument and judgment data stays in ordinary dictionaries and lists.
JSON parsing follows the standard library, including keeping the last value for
duplicate keys. Serialization rejects non-finite numbers with allow_nan=False.

## Domain protocols and Runner scope

Environment is a structural protocol with one `run()` method. `UserSimEnv(Environment)`
in agentinstruct.environment implements the conversation loop. Pass an
implementation instance to Runner; it must implement async run(task, *, client=None)
and perform domain work into the supplied
Episode. UserSimEnv alternates Agent turns, records them and optionally verifies.
Runner assigns the output path, invokes, saves and collects. Errors propagate and
stop the batch after saving the collected trace. Replace Environment(task).run()
with a supplied instance or the default UserSimEnv.

UserSimEnv cycles through Task.agents.items(), records each reply and optionally
verifies the conversation. It rejects returned Tool calls. Task has no segments
or deadline settings. Applications can wrap execution in asyncio.timeout when needed.
Direct Generator/Evaluator adapters customize conversation generation/evaluation.

The speculative resources= API and runtime verifier-dictionary assembly are
removed. Applications own async contexts around their batch. Task.verifier takes
a constructed Judge or an Evaluator implementing evaluate(messages) -> Judgment.
Agent.reviewer accepts the same protocol. Domain evaluators need no client/model
attributes; supply validated Judgment values. Built-in SDK clients remain borrowed.

Agent(generator=...) accepts a plain Generator implementing generate(history,
*, client, role, instruction) returning one unreviewed Message. Review and revisions
run inside Agent.generate. Move former Agent.generate subclass overrides into plain
Generator classes and pass their instances with generator=. Task-file custom
references instantiate these classes without arguments; their invocation receives
the active instruction, role and client. Scripted records use the same interface.
Task/Episode remain concrete data owners.

Agent has generate and private _review methods. Generate applies the optional
reviewer; the revision loop allows one initial sample
plus max_revisions replacements. Rejected drafts and feedback stay out of accepted
history. Exhaustion raises ReviewExhausted; there is no acceptance fallback.
UserSimEnv records approved conversation messages and passes accepted history to
the next Agent. Each call to generate has a fresh revision budget.
Agent has no Episode dependency or proposal/review recording. Drafts and feedback
remain local to generate. A leading system Message overrides the Agent's base instruction for
that call; otherwise generate prepends the base instruction.

Agent no longer accepts temperature, max_tokens, reasoning, output_schema,
extra_body or accept_on_revision_exhaustion. Task-file model declarations accept
name and provider. Custom generation can supply additional inference behavior when
needed. Model errors propagate from the SDK; Agent adds no error classification or
model-call evidence layer.
Agent's `api` selector and Responses translation are removed. Task files must
select Chat Completions for Agents; the loader rejects a different API explicitly.
Draft/review events and their historical readers are retired.
