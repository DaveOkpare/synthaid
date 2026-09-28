# agentinstruct

A Python framework for generating verified traces from agent interactions.

Task Package validation, compilation, deterministic single-Agent and dialogue
generation, reviewed private function Tools, per-Agent Review and revision,
final Verification, reverification, sequential JSON/JSONL Seed collections,
and native/OpenAI JSONL export
are available through the typed library
and CLI. Further capabilities follow the
[V1 specification](.scratch/v1-agent-trace-generation/spec.md).

## Generate a Trace

Run the [scripted example](examples/scripted-single/task.toml) without network
access or model credentials:

```sh
uv run agentinstruct run examples/scripted-single --output runs --json
```

The `run` command delegates to the same library lifecycle as:

```python
import asyncio
from agentinstruct import Runner, TaskPackage, export_native, load_trace


async def main():
    result = await Runner(output_dir="runs").run(
        TaskPackage.load("examples/scripted-single")
    )
    trace = load_trace(result.traces[0].path)
    print(trace.conversation[0].message.content)
    export_native([result.traces[0].path], "native.jsonl", statuses={"unverified"})


asyncio.run(main())
```

`generate(package, runner=...)` delegates to `Runner.run`; `generate_sync` wraps
the same operation for synchronous scripts. Use the asynchronous API inside an
existing event loop. Both accept a `seed_path` override, equivalent to CLI
`--seed`. `--json` returns the Run identity, ordered Trace references, and all
five terminal status counts. A finished Run containing only accepted, rejected,
or unverified Traces exits 0. Invalid or failed attempts and source failures exit
1; Task Package validation failures before Run creation exit 2.

Each execution creates a fresh Run, Trace, Agent, Reviewer, Environment, Interaction,
recorder, and Conversation. `type = "scripted"` Agents consume literal
`responses` strings without calling a Provider. Library callers can supply
`Runner(agent_factory=...)` with a factory accepting an `AgentPlan`; each fresh
Agent implements `async generate(observation)` and returns a `Message` or ordered
list of Messages. The Observation contains the rendered instruction and accepted
history. A custom `environment_factory` may implement asynchronous `setup` and
`run`, with optional `finalize`; it receives an immutable `TaskContext` and Agent
facades that open Interactions. Factories must construct new instances per call.

The local Run directory contains an authoring-file snapshot, manifest, and Trace
index. Each Trace retains its rendered Run Plan, full Seed data and origin,
accepted Message Commits, separate execution Events, component references and
available source digests, timing, and generation outcome. A complete `trace.json`
is persisted before its index reference is published. `load_trace` returns an
immutable snapshot; native JSONL export reads these persisted snapshots and
needs no live Runner or original package.

Generation without a configured Verifier is **unverified**, with a separate
`terminated` or `truncated` generation outcome. Export requires explicit selection
of `unverified` or other non-accepted statuses; its default selects only accepted
Traces. Live model adapters arrive in later tickets.

## Run a Seed collection

The [offline collection example](examples/seed-collection/task.toml) processes two
JSONL records using fresh scripted Agents and deterministic Verification:

```sh
uv run agentinstruct validate examples/seed-collection --json
uv run agentinstruct run examples/seed-collection --output runs --json
uv run agentinstruct run examples/seed-collection \
  --seed examples/seed-collection/seeds.json --fail-fast --output runs --json
```

A JSON object supplies one Seed; a JSON array supplies one Seed per element.
JSONL supplies one Seed per nonempty line. Processing follows source order.
Origins retain the source path and a one-based record position: an array element
position or physical JSONL line number, including intervening blank lines.
The configured `[seed] id_variable` names a declared Variable containing a
nonempty string or integer. Otherwise the Seed ID is a canonical content hash,
independent of object-key ordering. Reusing an ID within one Run produces an
invalid attempt. Every attempt receives a fresh Trace ID, including duplicates
and reruns of the same Seed.

```python
from agentinstruct import Runner, TaskPackage, generate_sync, export_openai

package = TaskPackage.load("examples/seed-collection")
report = package.validate()  # Compiles all records without runtime components.
print(report.to_dict())
result = generate_sync(package, runner=Runner(output_dir="runs"), fail_fast=False)
print(result.status, dict(result.counts))
export_openai([trace.path for trace in result.traces], "accepted.jsonl")
```

`Runner.run`, `generate`, and `generate_sync` all accept `seed_path` and
`fail_fast`. Each valid Seed compiles to its own immutable Run Plan. Each Trace
gets fresh Agent, Reviewer, Tool, Environment, Verifier, Interaction, and Task
Step state. Its terminal generation snapshot, any Verification sidecars, and
index entry are durable before the next Seed compiles or executes.

By default, invalid and failed attempts are recorded and processing continues.
`fail_fast=True` or CLI `--fail-fast` stops after the first **invalid or failed**
attempt; rejected quality decisions and unverified Traces continue. The returned
Run status is `finished`, `stopped` for fail-fast, or `failed` for a source or
storage-publication error.
Counts and ordered references include every attempted record, including partial
failed generation. These invocation summaries remain unchanged by reverification.

Malformed JSONL records, non-object array elements, duplicate IDs, missing
Variables, and rendering failures become invalid Traces with no Conversation.
Their standalone snapshots retain Task identity/digest, full available input in
`seed_record` with origin and digest, raw malformed text when needed, and precise
failure Events. `run_plan` is empty and no executable `run-plan.json` is invented.
They can be exported natively but never become empty OpenAI training records.
Source errors that prevent reliable enumeration, such as malformed array syntax
or an unreadable file, fail the Run and retain its available Traces and manifest
diagnostic. Package-wide validation still precedes Run creation.
If storage cannot publish a complete Trace/index pair, generation stops before
the next Seed; available snapshots and the failure diagnostic are retained where
the storage remains writable.

`validate --json` returns `plans`, ordered per-record diagnostics, and valid/invalid
counts for a collection. A source error also appears as `source_error`; already
compiled records remain in the report. A single valid record additionally retains
the existing `plan` field. `TaskPackage.compile()` remains the one-record API and
rejects sources with zero or multiple records. CSV, directory sources, Python
iterables, and Seed JSON Schema validation arrive in ticket 11.

## Generate and export a dialogue

The [scripted dialogue](examples/scripted-dialogue/task.toml) runs without network
access or credentials:

```sh
uv run agentinstruct run examples/scripted-dialogue --output runs --json
```

Set `[environment]` to `type = "dialogue"` and declare exactly the `user` and
`assistant` Agents, each with an explicit `target` Boolean. Exactly one must be
the Target Agent; either participant can be the target. `initiator` selects the
opening participant (default `user`), after which the Environment alternates
Interactions. Both participants observe the full accepted shared Conversation
in occurrence order. Relaying a reply references its existing Message Commit.

`max_rounds` defaults to 10 and bounds pairs of participant turns: at most twice
that many Interactions, regardless of initiator or Messages per Action. Reaching
the cap produces `truncated/max_rounds`. An optional positive `timeout_seconds`
bounds setup and generation together, and grants finalization its own equal
timeout. A framework deadline produces `truncated/timeout`; accepted partial
history stays in the Trace. Agent or Environment exceptions produce `failed`.

For the current single-step dialogue, the target can return
`Message(role="assistant", content="Done.", control="complete")`. The completion
proposal takes effect only after that Message is accepted and persisted, producing
`terminated/completed`, even on the last allowed turn. A scripted target may use
`{ content = "Done.", control = "complete" }` in its `responses` array. Plain text
and script exhaustion never signal completion; exhaustion fails the Trace. This
interim Message control will evolve into reviewed framework control Tool calls
with Task Steps in ticket 09. The single-Agent Environment completes after its
one accepted Interaction.

Export one or more persisted Trace directories (or `trace.json` paths) returned
by `run`:

```sh
uv run agentinstruct export runs/<run-id>/traces/<trace-id> \
  --format openai --status unverified --output dialogue.jsonl
```

`--format native` exports complete Trace snapshots. Both formats select only
`accepted` by default; repeat `--status` to explicitly select other statuses.
`--json` reports the exported count. OpenAI JSONL contains one `messages` array
per nonempty selected Trace: Target Agent replies map to `assistant`, and shared
replies from the other participant map to `user`. Native IDs, control metadata,
and Events stay out of training Messages. The Python equivalent is
`export_openai(trace_paths, "dialogue.jsonl", statuses={"unverified"})`.

## Review and revise Messages

The [reviewed dialogue](examples/reviewed-dialogue/task.toml) rejects an empty
scripted greeting, accepts its revision, and verifies the completed Trace offline:

```sh
uv run agentinstruct run examples/reviewed-dialogue --output runs --json
```

Review is optional and configured independently for each Agent. Add
`agents/<agent-id>/reviewer.md` for its stable instructions and
`agents/<agent-id>/rubric.toml` for weighted Criteria and a threshold, using the
same Rubric format as final Verification. Reviewer instructions may use declared
Variables; they are strictly rendered before generation and retained in the Run
Plan. Configure the policy in `task.toml`:

```toml
[agents.user.reviewer]
type = "custom"
max_revisions = 1
accept_on_revision_exhaustion = false
```

For custom Review, pass `Runner(reviewer_factory=...)`. The factory receives a
`ReviewerPlan` and constructs a fresh instance per Agent per Trace implementing
`async review(request: ReviewRequest) -> ReviewResult`. The request contains the
stable Reviewer `instruction`, active `rubric`, exact proposed `message`, accepted
`messages` visible to that Agent, and `agent_instruction`. Return
`ReviewResult(criteria={"criterion_id": True, ...}, feedback="...")`, or use a
sequence of ID/Boolean pairs. The framework validates complete, unique, known
Boolean verdicts and computes the weighted score. Review accepts an inclusive
threshold independently of final Verification.

A rejected Message stays in Events. The next generation request carries its
Reviewer feedback in `Observation.review_feedback`, separate from the accepted
`messages`; this field is cleared on the next ordinary turn. Rejected drafts and
review feedback never enter accepted history or the peer's Observation. Only
accepted Messages are committed and available for relay or training export.
Requests, verdicts, rejections, revisions, and errors retain review, Message,
Agent, and turn references; accepted commits retain their `review_id`.

`max_revisions` defaults to 1 and counts additional proposals after the initial
rejection; zero allows only the initial proposal. Every Message in an ordered
Action is reviewed separately. If a revision returns a list, its first Message
replaces the rejected proposal using that proposal's remaining revision budget.
Additional Messages are subsequent review subjects with their own budgets,
processed before any remaining Messages from the earlier Action.

Exhaustion normally yields `truncated/review_exhausted`. Explicitly enabling
`accept_on_revision_exhaustion` permits the final rejected conversational Message
to commit with `review_exhausted = true`; it never force-accepts a completion
control or Tool call. Missing, unknown, duplicate, or non-Boolean verdicts produce a
`failed/review_malformed` Trace, and Reviewer exceptions produce
`failed/review_execution`. Neither error retries or uses the fallback. Previously
accepted Messages remain durable if a later Message fails.

The example uses `type = "deterministic"` with a
`[agents.user.reviewer.checks]` mapping from its Criterion IDs to
`"nonempty_content"`. This built-in check only requires non-whitespace text; it
does not assess semantic quality. Custom Reviewers omit `checks`.
Provider-backed judges arrive in a later ticket.

## Review Tool calls before effects

The [function Tool example](examples/function-tool/run.py) runs an async Python
function through the same reviewed Interaction boundary as a custom Tool:

```sh
uv run python examples/function-tool/run.py --output runs
```

Declare Tools Task-wide in `task.toml`, with `description`, JSON `input_schema`,
and optional `output_schema`, then assign their identifiers using an Agent's
`tools` list. The [example package](examples/function-tool/task.toml) includes
both schemas and a deterministic Reviewer. Declarations and assignments are
compiled into the immutable Run Plan. Schema syntax and assignment references
are checked before generation; JSON Schema references use an offline registry
and never fetch remote resources.

Pass `Runner(tool_factory=...)` to construct fresh Tools from their `ToolPlan`.
A custom `Tool` exposes `id`, `description`, `input_schema`, `output_schema`,
`execution_errors`, and
`async call(args, context) -> JsonValue`; its declaration must match the compiled
plan. `FunctionTool(plan, async_function)` adapts a function with that same
arguments/context signature. Its provenance records the wrapped callable's
identity and available source digest. Explicit import-reference loading comes
in a later ticket; the example wires its runtime factories in Python.

The Agent receives only its assigned `ToolPlan` declarations in
`Observation.tools`. It proposes an assistant `Message` with a `tool_calls`
tuple, for example:

```python
Message(
    "assistant",
    tool_calls=(ToolCall("call-1", FunctionCall("lookup", {"label": "Ada"})),),
)
```

`FunctionCall.arguments` stays structured JSON, copied into immutable containers;
it is not a provider wire-format JSON string. `ToolContext` supplies the invoking
`actor_id`, Task/Seed/Run/Trace identities, extracted Variables, and turn/call
identifiers, without exposing storage or credentials.

The Tool-call Message gets its own review and revision budget. Rejection records
Events without committing or executing the call. Acceptance durably commits the
private call **before** assignment and argument validation, then executes the
Tool. Its result must be JSON data and satisfy any output schema; the framework
commits a private `role="tool"` Message with the matching `tool_call_id`. Results
are not LLM-reviewed. The Agent then observes that accepted exchange and proposes
its independently reviewed conversational reply.

A Tool-call Message must be the **last pending Message** in an ordered Action.
For example, `[conversational_message, tool_call_message]` is valid, while
`[tool_call_message, conversational_message]` fails before the Tool call commits
or executes. This rule also applies to revised Actions, including Messages still
pending from the original Action, and to Actions generated after a Tool result.
Previously accepted Messages remain durable. Every successful Tool exchange
triggers a fresh Agent generation request before any later reply or completion
control can be accepted; pending Messages are never silently dropped or reordered.

Only the invoking Agent sees the private exchange. The peer sees the later
accepted shared reply, and OpenAI export includes private calls/results only
when their owner is the Target Agent. Assignment, argument, execution, and result
failures retain accepted intent with typed `tool_*` reasons and linked Events.
An exhausted Tool-call or control-action review never uses conversational fallback.

Multiple calls in one Message are reviewed **together, exactly as proposed**,
then executed sequentially in their declared order. Each validated result commits
before the next call starts. Call IDs must be nonempty and unique across accepted
calls by that Agent; another Agent may use its own identical IDs. A later failure
or rejected reply retains the accepted call and already committed results.

Tools default to `execution_errors = "fail"`. A Tool may explicitly declare
`execution_errors = "result"` in `task.toml` to represent execution exceptions as
private results using this fixed contract:

```json
{"error":{"kind":"execution","exception":"ValueError"}}
```

The `error` object follows the `ToolExecutionFailure` type. The framework records
the exception class without exposing exception text in
Agent context. This error contract is independent of `output_schema`, which
validates successful output. The Agent observes the failure through the matching
`tool_call_id`, and remaining calls proceed in order. Assignment, argument,
malformed-output, unsupported-action, and persistence failures do not become
successful error results. The failure policy is part of the immutable Tool Plan
and must match the runtime Tool declaration.

`AgentTool(plan, agent_factory, instruction="...")` exposes a subordinate Agent
through the same Tool protocol. Its factory must create a fresh Agent per call.
The subordinate receives only the explicit instruction and one user Message
containing the current arguments as JSON. It receives no parent history or Tool
assignments, and must return one assistant Message containing valid JSON that
satisfies the Tool's output schema. A singleton list is also accepted. Nested
Tool calls, Tool-result Messages, completion controls, and multiple replies fail
without causing further effects. Factory identity and available source digest
are retained in Trace provenance. Normal subordinate execution exceptions follow
the declared failure policy; malformed replies fail with `tool_result`.

The [multi-Tool example](examples/multi-tool/run.py) uses isolated subordinate
Agents for three reviewed calls, retains a typed failure for the second, and
continues to the third without network access:

```sh
uv run python examples/multi-tool/run.py --output runs
```

## Verify and reverify Traces

The [verified example](examples/verified-single/task.toml) generates and verifies
a Trace without network access or credentials:

```sh
uv run agentinstruct run examples/verified-single --output runs --json
uv run agentinstruct export runs/<run-id>/traces/<trace-id> --output accepted.jsonl
uv run agentinstruct reverify runs/<run-id>/traces/<trace-id> --json
```

Enable Verification in `task.toml` and declare its weighted Criteria in
`verifier/rubric.toml`. The example uses the built-in deterministic checks:

```toml
[verifier]
type = "deterministic"
timeout_seconds = 10.0

[verifier.checks]
has_reply = "nonempty_conversation"
completed = "generation_terminated"
```

Its separate Rubric file contains:

```toml
threshold = 1.0

[[criteria]]
id = "has_reply"
description = "The Conversation contains an accepted reply."
weight = 3.0

[[criteria]]
id = "completed"
description = "Generation terminated normally."
weight = 1.0
```

Criteria must have unique portable IDs and finite positive weights with a finite
total. Thresholds range from zero to one inclusive. The framework computes the
passing weight divided by total weight: passing only `has_reply` scores `0.75`.
A score at or above the threshold is accepted; a lower valid score is rejected.
The two built-in checks evaluate structural completion, not content quality.
Each configured deterministic check must correspond to exactly one Criterion.

For domain-specific code or a judge-shaped extension, use `type = "custom"`
without `[verifier.checks]` and provide `Runner(verifier_factory=...)`. Each
factory receives the immutable `VerifierPlan` and constructs a fresh `Verifier`
implementing `async verify(trace: TraceSnapshot) -> VerificationResult`. Return
`VerificationResult(criteria={"has_reply": True, "completed": False}, feedback="...")`.
The result may also contain a sequence of `(criterion_id, bool)` pairs. Missing,
duplicate, unknown, and non-Boolean verdicts are errors. Factory exceptions,
verification exceptions, timeout, and malformed results record an **unverified**
attempt with error details and no invented false verdicts. Provider-backed judges
arrive in a later ticket.

Verification starts after Environment finalization and durable generation sealing.
Each attempt records a schema version, sequence, unique ID, Verifier identity and
available source digest, full policy, verdicts, score or error, feedback, and timing
in `verification/<attempt-id>.json`. Generation files (`trace.json`, Run Plan,
Conversation, and Events) are never rewritten by reverification. A failed or
invalid generation remains failed or invalid even if its Verifier returns a
passing score.

The async library operation is `await reverify(trace_path)`. Supply
`plan=new_verifier_plan` and `verifier_factory=...` to apply a new custom policy;
otherwise the original persisted Verifier Plan is used. The CLI accepts multiple
Trace paths and `--package <task-package>` to use that package's Verifier policy.
It exits 1 for an unverified attempt or an operation error, 2 for an invalid
override package, and 0 for valid accepted or rejected decisions.

`load_trace` assembles a complete immutable snapshot with every attempt. It
derives status from the latest valid attempt; a later error stays visible in
`trace.verification` without replacing a previous valid decision. Both exporters
use that status by default. Select an older valid attempt with
`verification_id=attempt.id` in `load_trace`, `export_native`, or `export_openai`,
or `--verification <attempt-id>` in the export CLI. Unknown or unverified attempt
IDs are rejected. Native export embeds all attempts so its snapshots can be read
independently of the original Run directory. Run Results, manifests, and the Run
index retain the original invocation's counts; inspect the Trace for current
verification status.

## Retain history across Task Steps

Declare ordered steps under `[task]`:

```toml
[task]
id = "stepped-dialogue"
version = "1"
steps = ["collect", "conclude"]
```

Every Agent participates in every step and requires
`steps/<step-id>/agents/<agent-id>/instruction.md`. Its rendered base instruction
stays active; only the current step's addition is appended. Optional step
`rubric.toml` files append `[[criteria]]` to that Agent's base Rubric. Criterion
IDs must be unique within each composed Rubric. Step files cannot set a
`threshold`; the base Rubric's reviewer threshold applies throughout. Step
Criteria require a configured Reviewer. A deterministic Reviewer's `checks`
must cover the union of its base and step Criterion IDs; only active Criteria
are scored. All step templates render before the first generation call.

Accepted Conversation and each Agent's private Tool history persist across
steps. The Target Agent receives the framework's `advance_step` Tool with the
next step ID in its input schema, or `complete_task` in the final step. These
identifiers are reserved against Task Tool declarations. Each control must be
the only Tool call in its Message and the last pending Message in its Action.
The same review, revision, durable intent, and private-result rules apply as
for ordinary Tools. Rejection cannot advance or complete a Task, including
when conversational exhaustion fallback is enabled.

An accepted advancement replaces the active additions for all Agents. Its call
and result retain the step that authorized them; `step_started` and subsequent
proposals reference the new step. `Observation.step_id`, `ReviewRequest.step_id`,
`ToolContext.step_id`, Message Commits, and Events expose that attribution.
Accepted completion produces a private result, then requests a final reply under
the final step's Rubric with no Tools available. The existing
`Message(control="complete")` shorthand remains supported only for Tasks that
omit steps; stepped Tasks use `complete_task`.

Environments receive immutable ordered IDs in `TaskContext.steps` and propose
controls through the Target Interaction:

```python
async with agents["assistant"].interaction(task) as interaction:
    reply = await interaction.control(task.advance_step("conclude"))
    # The Target Agent sees the result and generates a separately reviewed reply.
    final = await interaction.control(task.complete_task())
```

`TaskContext` has no recorder or history mutation API. Its helper methods only
construct proposals; `Interaction.control()` applies the same acceptance loop
as Agent proposals. Returning a terminated outcome without accepted completion
truncates a stepped Task as `incomplete_steps`. The single-agent Environment
uses `max_turns` to bound stepped execution; dialogue retains its `max_rounds`
limit across all steps.

Run the [offline stepped dialogue](examples/stepped-dialogue/run.py):

```sh
uv run agentinstruct validate examples/stepped-dialogue --json
uv run python examples/stepped-dialogue/run.py --output /tmp/stepped-dialogue
```

It compiles two phases for both participants, reviews the Target's Tool calls
and replies, and reuses its private greeting lookup in the final phase. Its
deterministic checks demonstrate the acceptance mechanics; they do not claim
semantic grading. A final Verifier is omitted, so the terminated Trace is
`unverified`.

## Validate a Task Package

The [single-agent example](examples/single-agent/task.toml) contains `task.toml`,
one JSON Seed, and `agents/assistant/instruction.md`. Validate it without model
calls or credentials:

```sh
uv run agentinstruct validate examples/single-agent
uv run agentinstruct validate examples/single-agent --json
uv run agentinstruct validate examples/single-agent --seed /path/to/seed.json
```

`--json` emits compiled Run Plans and per-record diagnostics; a single valid
record also has a `plan` field. Validation failures exit with status 2. The default Seed path is
relative to the Task Package; an explicit `--seed` override is relative to the
working directory. Validation reads inputs without creating Run outputs.

The equivalent Python API is:

```python
from agentinstruct import TaskPackage

package = TaskPackage.load("examples/single-agent")
plan = package.compile()  # Or package.compile(seed_path="/path/to/seed.json")
print(plan.agents["assistant"].base_instruction)
print(plan.digest)
print(plan.to_json())
```

The current implementation supports schema version `"1"`, a `single` or `dialogue`
Environment, exactly one explicit Target Agent, the `local` Runtime, and JSON
object/array or JSONL Seeds. Every Agent requires `agents/<id>/instruction.md`. Unknown configuration
fields and unsupported component selections fail validation. Task Steps are
optional; a Task without declared steps omits the `steps/` directory.

`[variables]` maps template aliases to dot paths through nested JSON mappings.
Array indexing and empty path segments are unsupported. Every selector must
resolve, and instruction templates use strict, sandboxed Jinja. Templates may
interpolate JSON values; Python methods and other runtime attributes are rejected
(use Jinja filters such as `name | upper`). Iterator filters produce data lists,
and the nondeterministic `random` filter is unavailable. A `[seed]`
`id_variable` names a declared alias containing a nonempty string or integer;
otherwise the Seed ID is its canonical content hash.

`[model]` supplies the provider identifier, model name, and optional `temperature`
and `max_tokens`; an Agent's `[agents.<id>.model]` may override those fields.
Provider declarations support `openai`, `openai-compatible`, and `vllm` identities
for compilation only. They are not a claim of implemented runtime adapters.
OpenAI defaults to the `responses` API surface; the other types default to
`chat_completions`. An explicit `api` selects either surface. Credentials use
`api_key_env` references, never inline values. Validation neither reads those
environment variables nor imports providers. Connection URLs cannot contain
credentials, query strings, or fragments.

Run Plans separate Task identity, Seed data and origin, extracted Variables,
Provider and Agent settings, Environment, Runtime, and provenance. Their nested
data is immutable; `to_dict()` returns an independent JSON-compatible copy.
Digests use canonical sorted JSON and exclude generated execution identities.
The compiler prepares inputs for one Trace attempt; the Runner assigns
fresh Run and Trace IDs when executing them. Keep credentials out of Seed data
and instructions, which are intentionally retained as Task inputs.

## Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
uv sync
uv run agentinstruct --help
uv run agentinstruct --version
```

Python 3.13 or newer is required. `.python-version` selects Python 3.13 for
contributors; uv can install it if it is missing. `uv sync` installs the package
and development dependencies into `.venv`. Commit `uv.lock` with dependency
changes, using `uv add` for runtime dependencies and `uv add --dev` for development
tools. Jinja supplies instruction templating, Pydantic validates configuration,
and jsonschema validates Tool contracts with an offline referencing registry.

Run the quality checks from the repository root:

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
```

Ruff is the sole linter and formatter. Apply formatting with `uv run ruff format .`;
apply lint fixes explicitly with `uv run ruff check --fix .`. Mypy checks the
library and tests in strict mode. Run an individual test file while developing
with `uv run pytest tests/test_cli.py`.

CI runs these checks with locked dependencies on Python 3.13. The workflow uses
uv 0.11.26, matching the initialized build backend. `uv build` produces a source
distribution and a wheel in `dist/`, including the `py.typed` marker. Package
contents follow the [uv build backend defaults](https://docs.astral.sh/uv/concepts/build-backend/#file-inclusion-and-exclusion);
research, prototypes, development caches, and generated Runs are outside the
distributed package.

## Project layout

- `src/agentinstruct/`: supported library and CLI code.
- `tests/`: public Runner lifecycle, persisted export, CLI, and import-safety
  checks. Tests use deterministic extensions and do not call external services.
- `.scratch/`: the V1 specification and implementation tickets.
- `CONTEXT.md` and `docs/adr/`: domain vocabulary and architectural decisions.
- `research/` and `prototypes/`: design evidence, outside the runtime package.
