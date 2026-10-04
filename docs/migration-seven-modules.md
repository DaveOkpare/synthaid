# Migrate to the seven generation modules

This is a deliberate Python API change. Removed interfaces have no aliases.
Historical saved Trace JSON remains readable through Episode.load and Inspector.

| Former API or ownership | Replacement |
| --- | --- |
| Runner(environment, task dictionaries) | Runner(list[Task], output_dir=..., client=..., environment=domain_instance) |
| Environment.setup(task), run(task), conversation(episode), async context ownership | Environment is a protocol: async run(task, *, client=None); Runner opens the Episode and invokes an implementation instance; Environment owns execution/deadline/finalization |
| Environment allocates/returns Episode; environment.output_dir | Task creates episode immediately; Runner opens output_dir / episode.id; Environment.run returns None after its execution/finalization; Runner collects the Episode |
| Separate Agent definition/runtime or AgentObservation | Construct Agent directly; supply custom sampling with generator=domain_object |
| Agent.turn(episode) and single-sample Agent.generate | Agent.generate(history, *, client=None, role="assistant") returns a reviewed proposal; Environment records acceptance and executes Tools |
| Arbitrary participant names, Agent.id/target, separate assistant/user fields | Task.agents with required assistant and optional user; role is invocation-local |
| Task-level tools or global Tool lookup | Agent.tools: explicit sequence of Tool objects, default empty |
| FunctionTool and Tool subclasses with contexts | Tool(async_function, id=..., input_schema=..., output_schema=...); custom factories return Tool |
| Provider, ProviderRequest/Response, ChatCompletionsProvider, ResponsesProvider | Application-owned AsyncOpenAI; Agent supports Chat Completions only; Judge retains its API selection |
| Reviewer/Verifier classes and request/result factories | Judge(check=...) or Judge(client=..., model=..., prompt=..., rubric=...) |
| Taskset or global message_judge / episode_judge | list[Task]; Agent.reviewer and Task.verifier |
| Root Criterion/Rubric/ReviewResult exports | Criterion, Rubric, Judgment from agentinstruct.judge |
| Root Message/FunctionCall/ToolCall exports | Supporting values from agentinstruct.episode |
| LocalRunStore, RecordedTrace, TraceSnapshot, load_trace | Episode, Episode.load, and optional Inspector |
| TaskPackage, Seed, component registries, generate/generate_sync | adapters.task_files.compile_records/load_tasks; Runner.run or asyncio.run in the application |
| Independent Episode per authored step | Ordered Task.segments sharing one Episode and private history |
| Plans, lifecycle/control Tools, reset/step methods | Ordinary Task input/segments and Environment scheduling |
| Structured-output subsystem | Tool input/output schemas and Judge Rubric checks |

Agent construction is inert. A custom generator must keep execution
state local or in the supplied Episode/history; externally mutable dependencies
need explicit application ownership. The same configured Agent or Judge can serve
independent concurrent Tasks. A completed Task is one recorded execution and cannot
silently reset, append, or overwrite its output.

Clients are borrowed through Runner/Environment/Agent and Judge. Explicit Agent and
Judge clients retain their declared dependency. Initialize and close each endpoint's
client in the application's outer async scope. Configure SDK retries explicitly;
core model calls force max_retries=0.

Task files preserve assistant/user syntax, templates, source formats, Tool catalogs,
review rubrics, and steps. Target flags are allowed only when consistent with those
fixed roles. Other roles and custom scheduling references produce migration errors;
use direct structural Environments for custom scheduling. Custom generation references
must name plain Generator classes with no-argument constructors; custom Judge references name
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

## Domain protocols and Runner scope

Environment is now a structural protocol, with a stateless UserSimEnv implementation
in agentinstruct.environment. Pass an implementation instance to Runner; it must
implement async run(task, *, client=None) and perform domain work into the supplied
Episode. Its run method owns beginning execution, deadlines/failures, sealing and
optional verification. Runner only opens, invokes and collects. Custom Environment
errors propagate directly. Replace Environment(task).run() with a supplied instance
or the default UserSimEnv; open task.episode before standalone execution.

Code written against the earlier Runner-owned lifecycle must implement that policy
in its Environment. Direct Generator/Evaluator adapters can keep UserSimEnv's
built-in safeguards while varying domain generation/evaluation.

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
UserSimEnv commits approved proposals before executing their declared Tools and
calls generate again with Tool results. Each call has a fresh revision budget.
Agent has no Episode dependency or proposal/review recording. Drafts and feedback
remain local to generate. A leading system Message overrides the Agent's base instruction for
that call; otherwise generate prepends the base instruction.

Agent no longer accepts temperature, max_tokens, reasoning, output_schema,
extra_body or accept_on_revision_exhaustion. Task-file model declarations accept
name and provider. Custom generation can supply additional inference behavior when
needed. Model errors propagate from the SDK; Agent adds no error classification or
model-call evidence layer. Task records the Agent settings directly.
Agent's `api` selector and Responses translation are removed. Task files must
select Chat Completions for Agents; the loader rejects a different API explicitly.
Historical Episodes containing draft/review events remain readable.
