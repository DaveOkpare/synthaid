# Migrate to the seven generation modules

This is a deliberate Python API change. Removed interfaces have no aliases.
Runner writes the lean Episode as plain JSON. Historical trace loading is retired.

| Former API or ownership | Replacement |
| --- | --- |
| Runner(environment, task dictionaries) | Runner(list[Task], output_dir=..., client=..., environment=domain_instance) |
| Environment.setup(task), run(task), conversation(episode), async context ownership | Environment is a protocol: async run(task, *, client=None); Runner assigns its trace path and invokes an implementation instance; UserSimEnv records messages and optionally verifies |
| Environment allocates/returns Episode; environment.output_dir | Task creates episode immediately; Runner assigns output_dir / episode.id / trace.json; Environment.run returns None; Runner saves and collects the Episode |
| Separate Agent definition/runtime or AgentObservation | Construct Agent(model, instruction) with an OpenAI client |
| Agent.turn(episode) and single-sample Agent.generate | Agent.generate(messages=(), **options) returns the reviewed SDK response; UserSimEnv records accepted conversation messages |
| Arbitrary participant names, Agent.id/target, separate assistant/user fields | Task.agents with required assistant and optional user; role is invocation-local |
| Task-level tools or global Tool lookup | Agent.tools: explicit sequence of Tool objects, default empty |
| FunctionTool and Tool subclasses with contexts | Tool(async_function, id=..., description=..., input_schema=...); custom factories return Tool |
| Provider, ProviderRequest/Response, ChatCompletionsProvider, ResponsesProvider | Application-owned AsyncOpenAI; Agent and Judge use Responses |
| Reviewer/Verifier classes and request/result factories | Judge(rubric, model, client) or Judge(rubric, check=...) |
| Taskset or global message_judge / episode_judge | list[Task]; Agent.reviewer and Task.verifier |
| Root Criterion/Rubric/ReviewResult exports | Criterion, Rubric, Judgment from agentinstruct.judge |
| Root Message/FunctionCall/ToolCall exports | Message TypedDict from agentinstruct.episode; native SDK tool calls and response objects |
| LocalRunStore, RecordedTrace, TraceSnapshot, load_trace | Data-only Episode dataclass; Runner writes traces; plain JSON reads and optional Inspector |
| TaskPackage, Seed, component registries, generate/generate_sync | adapters.task_files.compile_records/load_tasks; Runner.run or asyncio.run in the application |
| Built-in steps, Tool execution and Task deadlines | Steps and Task deadlines are removed; custom Environments can execute Tools |
| Plans, lifecycle/control Tools, reset/step methods | Ordinary Task input and one UserSimEnv.run conversation loop |
| Structured-output subsystem | Tool parameter schemas for model calls and Judge Rubric checks |

Agent construction is inert. Each Agent retains its own history across generate
calls. Task creates a fresh Agent copy for each participant with an empty history;
clients, Tools and reviewers retain their configured references. The same Agent
configuration can therefore be supplied to independent concurrent Tasks.
Runner creates each Task's output directory
exclusively; reusing that output fails before generation. Episode itself is
ordinary mutable trace data.

Clients are borrowed through Runner/Environment/Agent and Judge. Explicit Agent and
Judge clients retain their declared dependency. Initialize and close each endpoint's
client in the application's outer async scope. Configure SDK retries explicitly;
Agent and Judge honor the supplied SDK client policy.

Task files preserve assistant/user syntax, templates, source formats, Tool catalogs,
review rubrics. Target flags are allowed only when consistent with those
fixed roles. Other roles and custom scheduling references produce migration errors;
use direct structural Environments for custom scheduling. Scripted/custom Agent
generators are removed; task-file Agents use models. Judges use models or check callables.
Custom Tool references name factories returning Tool.
Compilation validates these references syntactically without importing them.

## Task holds conversation data

Task has five fields: agents, input, verifier, max_turns and an automatically created
episode. Its only method validates the participant keys and turn limit and
creates fresh Agent copies.
Task input stays ordinary data. Task.agents contains fresh copies of the supplied
Agents so every participant starts with its own empty history.

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
to the function name. `schema()` returns a Responses function declaration;
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
The Message dataclass is replaced by a TypedDict with role and content.
Use `Message(role="user", content="Hello")` or an annotated dictionary literal.
FunctionCall and ToolCall wrappers are removed; use native SDK outputs. The redundant actor_id and control fields are removed;
UserSimEnv records the role from Task.agents and stops at max_turns.

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
Agent instructions and Evaluator implementations customize generation/evaluation.

The speculative resources= API and runtime verifier-dictionary assembly are
removed. Applications own async contexts around their batch. Task.verifier takes
a constructed Judge or an Evaluator implementing evaluate(messages) -> Judgment.
Agent.reviewer accepts the same protocol. Domain evaluators need no client/model
attributes; supply Judgment values. Built-in SDK clients remain borrowed.

## Agent calls the SDK directly

Use `Agent(model, instruction, tools=(), reviewer=None, max_revisions=1,
client=None)`. Agent and Judge use Responses only; remove their `api` arguments.
Configured servers must support `/v1/responses`.
Pass only new OpenAI messages to `generate(messages, client=..., **options)`;
Agent appends them to its private history and retains its outputs. Direct callers
use separate Agent instances for independent conversations.
Its return value is the SDK Response, including native tool calls,
reasoning items, refusal and incomplete status. Read reply text through `output_text`.
Agent does not normalize those outputs,
parse function arguments or execute Tools. Caller-supplied generation options are
forwarded to Responses, including `reasoning` for summaries and `text.format` for
structured output on compatible models. Streaming is not supported.

Generator, generator=, custom sampling classes and scripted task-file responses
are removed. Offline tests and demonstrations use an HTTP transport with the real
SDK. Remove task-file `provider.api`; model declarations accept name and provider.
The task-file loader rejects the removed API selector.

The revision loop allows one initial sample plus max_revisions replacements.
The reviewer receives history plus the current native output serialized into
dictionaries. Rejected drafts and feedback remain in that Agent's history;
exhaustion raises ReviewExhausted. Rejected tool proposals are passed back as
JSON text for revision,
so they do not create pending API tool calls. Accepted output is returned unchanged.
A leading system or developer message in the initial history overrides the Agent
instruction.

UserSimEnv records accepted role/content conversation messages. It supplies only
the latest published reply as a user message to the next Agent, adding Task input
on that Agent's first turn. It never reconstructs model history from the Episode.
Private tool calls, results and review feedback stay with their owning Agent.
Dialogue length uses max_turns; there is no message control field. Draft/review
events and historical readers remain retired.


## Judge grades a Rubric

Construct `Criterion(context, weight=1.0)` and `Rubric([criterion, ...], threshold)`.
Judge takes this Rubric and either a model/client or `check=` callable. Its public
`evaluate(messages)` method obtains pass/fail grades and optional feedback,
then divides the sum of passing weights by the sum of all weights. Use nonempty
criteria with positive weights. Acceptance uses `score > threshold`; equality
rejects. A threshold of 1.0 never accepts, so choose an explicit lower threshold.

Criterion IDs and descriptions are replaced by context. Judgment holds only
passed, feedback and score. Evidence, JudgeError,
timeout_seconds and custom validation helpers are removed. Configure timeouts and
retries on the SDK client; errors propagate directly. The SDK generates and parses
the structured grading response.

Set `Judge(..., prompt="...")` to customize the model's grading instructions.
Omitting it keeps the default pass/fail and feedback prompt. Task-file reviewers
and verifiers also accept an inline `prompt`, including template variables.

Code checks can be synchronous or asynchronous. They receive messages and return
`{"criteria": [True, False, ...], "feedback": "..."}` with one Boolean per criterion
in rubric order. Feedback defaults to an empty string when omitted. Judge applies
the same weights and threshold, without making a model request. Bare Booleans,
precomputed Judgments and criterion-ID mappings are replaced by this single shape.

In task files, use `type = "model"` or `type = "module:check_function"`, put each criterion's instructions in its context,
and specify the rubric threshold. Move reviewer.md and verifier/instruction.md
instructions into those contexts; separate judging instruction files are removed.
The former built-in deterministic check catalog and Judge timeout settings are removed.
