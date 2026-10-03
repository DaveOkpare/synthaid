# Migrate to the seven generation modules

This is a deliberate Python API change. Removed interfaces have no aliases.
Historical saved Trace JSON remains readable through Episode.load and Inspector.

| Former API or ownership | Replacement |
| --- | --- |
| Runner(environment, task dictionaries) | Runner(list[Task], output_dir=..., client=..., environment=Environment) |
| Environment.setup(task), run(task), conversation(episode), async context ownership | Environment(task, client=...).run(); custom structural classes implement that constructor and run |
| Environment allocates/returns Episode; environment.output_dir | Task creates episode immediately; Runner opens output_dir / episode.id; run returns None |
| Separate Agent definition/runtime or AgentObservation | Construct Agent directly; override generate(history, *, client=None, role="assistant", instruction=None) |
| Arbitrary participant names, Agent.id/target, separate assistant/user fields | Task.agents with required assistant and optional user; role is invocation-local |
| Task-level tools or global Tool lookup | Agent.tools: explicit sequence of Tool objects, default empty |
| FunctionTool and Tool subclasses with contexts | Tool(async_function, id=..., input_schema=..., output_schema=...); custom factories return Tool |
| Provider, ProviderRequest/Response, ChatCompletionsProvider, ResponsesProvider | Application-owned AsyncOpenAI; api="chat_completions" or "responses" on Agent/Judge |
| Reviewer/Verifier classes and request/result factories | Judge(check=...) or Judge(client=..., model=..., prompt=..., rubric=...) |
| Taskset or global message_judge / episode_judge | list[Task]; Agent.reviewer and Task.verifier |
| Root Criterion/Rubric/ReviewResult exports | Criterion, Rubric, Judgment from agentinstruct.judge |
| Root Message/FunctionCall/ToolCall exports | Supporting values from agentinstruct.episode |
| LocalRunStore, RecordedTrace, TraceSnapshot, load_trace | Episode, Episode.load, and optional Inspector |
| TaskPackage, Seed, component registries, generate/generate_sync | adapters.task_files.compile_records/load_tasks; Runner.run or asyncio.run in the application |
| Independent Episode per authored step | Ordered Task.segments sharing one Episode and private history |
| Plans, lifecycle/control Tools, reset/step methods | Ordinary Task input/segments and Environment scheduling |
| Structured-output subsystem | Agent.output_schema; Tool input/output schemas; Judge Rubric checks |

Agent construction is inert and immutable. A custom generator must keep execution
state local or in the supplied Episode/history; externally mutable dependencies
need explicit application ownership. The same configured Agent or Judge can serve
independent concurrent Tasks. A completed Task is one recorded execution and cannot
silently reset, append, or overwrite its output.

Clients are borrowed through Runner/Environment/Agent and Judge. Explicit Agent and
Judge clients retain their declared dependency. Initialize and close each endpoint's
client in the application's outer async scope. Configure SDK retries explicitly;
core model calls force max_retries=0. Native endpoint options belong in Agent.extra_body;
they cannot override history, Tools, storage, streaming, or continuation ownership.

Task files preserve assistant/user syntax, templates, source formats, Tool catalogs,
review rubrics, and steps. Target flags are allowed only when consistent with those
fixed roles. Other roles and custom scheduling references produce migration errors;
use direct structural Environments for custom scheduling. Custom Agent references
must name Agent subclasses using its constructor; custom Judge references name
message-check callables; custom Tool references name factories returning Tool.
Compilation validates these references syntactically without importing them.

Deterministic task-file checks evaluate accepted Messages: nonempty_content,
nonempty_conversation, assistant_present, and user_present. The former
`generation_terminated` check depended on a Trace wrapper and is rejected explicitly.
Generation outcome is now separately available on Episode.generation; an application
can apply an outcome policy after execution. Shipped structural-check examples use
assistant_present. This does not establish semantic correctness or full completion.

Output files are exclusively created. Generation seals once; verification appends
new sidecars and cannot promote failed/invalid generation. For standalone historical
JSON files, sidecars use `<filename>.verification/`; Episode directories use
`verification/`. Inspection retains historical participant identities and target
metadata, even when those old identities cannot be used in a new Task.

The optional CLI manifest indexes Episode directories directly under its output
root. Historical manifests/indexes remain readable. CLI reverification requires an
explicit task package policy; direct callers can provide a constructed Judge.
The TUI and vLLM launcher remain in their optional namespaces.
