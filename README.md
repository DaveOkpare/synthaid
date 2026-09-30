# agentinstruct

A Python framework for generating verified traces from agent interactions.

Task Package validation, compilation, deterministic single-Agent and dialogue
generation, reviewed private function Tools, per-Agent Review and revision,
final Verification, reverification, sequential file and iterable Seed collections,
ordered Task Steps, persisted inspection, and native/OpenAI JSONL export are
available through the typed library and CLI. OpenAI Responses/Chat Completions and
explicit compatible/vLLM profiles share the same reviewed execution boundary.
The pinned vLLM candidate remains unverified until its opt-in live conformance
report passes; the [V1 specification](.scratch/v1-agent-trace-generation/spec.md)
describes the supported scope.

## Complete an offline workflow

From the repository root, the [release example](examples/release-workflow/task.toml)
produces two accepted Seeds through a reviewed two-Step dialogue and private Tool
calls. Its explicit Python components require no inference service or credentials:

```sh
uv sync --locked
export PYTHONPATH="$PWD/examples/release-workflow${PYTHONPATH:+:$PYTHONPATH}"
uv run agentinstruct validate examples/release-workflow --json
uv run agentinstruct run examples/release-workflow --output /tmp/agentinstruct-runs --json
```

Use the Run `path` printed by `run` as `RUN`, and one returned Trace `path` as
`TRACE`:

```sh
RUN=/tmp/agentinstruct-runs/<run-id>
TRACE="$RUN/traces/<trace-id>"
uv run agentinstruct inspect "$RUN"
uv run agentinstruct inspect "$RUN" --tui
uv run agentinstruct export "$RUN" --format native --output /tmp/native.jsonl
uv run agentinstruct export "$RUN" --format openai --output /tmp/accepted.jsonl
uv run agentinstruct export "$RUN" --seed-id ada --output /tmp/ada.jsonl
uv run agentinstruct reverify "$TRACE" --package examples/release-workflow --json
```

In the terminal inspector, use `trace 1`, `conversation`, `tools`, `reviews`,
`verification`, `next`, and `quit`. Reverification appends evidence without changing
sealed generation. The fixture's optional `--seed examples/release-workflow/coverage.jsonl`
adds deliberate rejected, unverified, invalid and failed records; that Run exits 1
while retaining all six attempts. Default exports still include only the two
accepted records. Repeat `--status` to include other statuses intentionally.

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
Traces. Model Agents can generate through Responses or Chat Completions.

## Load custom components

Built-in identifiers use the small `BUILTIN_COMPONENTS` registry. Explicit Python
references use `module:Class`, including nested class attributes; a failed explicit
lookup reports that exact reference and never falls back to a built-in. Modules
must already be importable. There is no discovery or automatic installation.

| Component | Built-in identifiers | Custom class constructor | Required async methods |
| --- | --- | --- | --- |
| Agent | `model`, `scripted` | `Class(agent_plan)` | `generate(observation)` |
| Environment | `single`, `dialogue` | `Class()` | `setup(agents)`, `run(task, agents)` |
| Tool | `function`, `agent`, `custom` | `Class(tool_plan)` | `call(arguments, context)` |
| Reviewer | `model`, `deterministic`, `custom` | `Class(reviewer_plan)` | `review(request)` |
| Verifier | `model`, `deterministic`, `custom` | `Class(verifier_plan)` | `verify(trace)` |

Set the component's `type` to its explicit reference, for example:

```toml
[environment]
type = "my_extension:RoundTable"

[agents.target]
type = "my_extension:Participant"
target = true

[agents.target.reviewer]
type = "my_extension:Reviewer"

[verifier]
type = "my_extension:Verifier"
```

`TaskPackage.load` imports only the requested definitions, checks constructor and
async method signatures, and snapshots their source digests. It does not construct
instances or model clients. Extension modules must keep imports free of runtime
work. The Runner creates fresh instances for each Trace and validates instance
protocols before use; Tool declaration properties are checked after construction.
The existing injected factories continue to work, including `type = "custom"`
Reviewer/Verifier declarations and Tool declarations without a type. Model
components retain their Runner-managed Provider construction.

A custom Environment has a no-argument constructor and receives `TaskContext`
and run-bound `Agents` through its hooks. The immutable context contains Task and
Seed identity, Variables, limits and Step controls. Ordinary async Python can open
any participant's `interaction(task)` and relay the accepted `last_reply` returned
by `turn()`. There is no public recorder, raw Run Plan or Provider client on these
facades. An optional `async finalize(task, trace)` hook receives the existing
immutable finalization snapshot. Custom scheduling retains the same review,
private Tool history, durable Message Commits and framework scoring boundaries.

The [offline custom-component Task](examples/custom-components/task.toml) uses
all five reference kinds with three participants, two Seeds, a rejected Tool
proposal followed by revision, and a final Verifier. Its Python module is explicit
and local; add that directory to the import path for these commands:

```sh
PYTHONPATH=examples/custom-components uv run agentinstruct validate examples/custom-components --json
PYTHONPATH=examples/custom-components uv run agentinstruct run examples/custom-components --output runs --json
```

Keep the module importable when running `reverify` on its saved Trace. Inspection
and export need only the saved artifacts. Explicit implementation files inside a
Task Package join its source snapshot; installed external components retain their
reference and source digest. Compiled Plans also retain `component_digests` in
provenance. Missing source text is represented by a null digest.

Function and subordinate-Agent Tool adapters also have explicit declarations:

```toml
[tools.lookup]
type = "function"
function = "my_extension:lookup"
description = "Look up a label."
input_schema = { type = "object" }

[tools.delegate]
type = "agent"
agent_factory = "my_extension:Subordinate"
agent_config = { label = "safe" }
instruction = "Return the configured label as JSON."
description = "Produce an isolated structured reply."
input_schema = { type = "object" }
```

A function reference must be an `async def(arguments, context)`. An Agent Tool
factory is synchronous, accepts one immutable configuration mapping, and returns a
fresh Agent for each call; a class with that constructor is also supported. Its
instruction is a literal string. The subordinate retains the existing isolated
Observation and no nested-effect contract. Native provenance records the actual
function/factory identity and source digest; Agent Tools also retain the instruction
and declared configuration. Configuration is JSON authoring data, so credentials
belong in runtime secret sources rather than these retained declarations.

## Generate through a Chat Completions Provider

For an opt-in live provider smoke, see the
[Doubleword medagent example](examples/doubleword-medagent/README.md). It uses two
non-personal scenario extracts, capped requests, a read-only Tool, structured
Verification, and persisted exports through the existing compatible adapter.

The [model example](examples/chat-completions/task.toml) selects
`api = "chat_completions"` explicitly. Replace its placeholder model name with a
model available to your account and set `OPENAI_API_KEY` in your runtime environment.
Credentials are read only when inference starts. Validation remains offline:

```sh
uv run agentinstruct validate examples/chat-completions --json
uv run agentinstruct run examples/chat-completions --output runs --json
```

For a compatible service, set `type = "openai-compatible"` and its `base_url`
(for example, `http://127.0.0.1:8000/v1`). Its default surface is Chat Completions.
Set `api_key_env` if the endpoint requires a credential; omit it for an endpoint
that requires no authentication. OpenAI defaults to `OPENAI_API_KEY` when the
reference is omitted. OpenAI uses the `responses` surface by default and supports
explicit Chat Completions; the framework never silently switches APIs. The example
is configuration guidance and has not been exercised against a live service.

`Provider` exposes `capabilities`, `async generate(ProviderRequest)`, and
`async aclose()`. Framework-owned requests contain ordered Messages, function
Tool definitions and choice, response-format requirements, inference controls,
and identity metadata. Responses contain one assistant proposal, finish state,
usage, request ID, latency, and allowlisted metadata. The adapter maps `max_tokens`
to the current Chat Completions `max_completion_tokens` field. It sends complete
accepted history with `store = false`, `stream = false`, and one requested choice.
Model Agents project their own accepted Messages as assistant Messages and other
participants as user Messages. Only the acting participant's private Tool history
and current review feedback enter its request. A generated Tool call still needs
review, durable commit, assignment checking, and schema validation before execution.

The Runner preflights every used surface before the first inference and closes its
Providers after each Trace, including failures and timeouts. Scripted Agents and
custom Agent factories do not construct unused Providers. Failures retain distinct
`ProviderError.kind` categories for authentication, authorization, rate limits,
timeouts, network, invalid requests, unsupported features, unavailable models,
server errors, malformed responses, and unknown errors. There are no automatic
retries or redirect/API fallbacks. Refused or incomplete proposals cannot authorize
Tool effects. Trace Events retain model-call identity, usage, latency and safe
metadata; resolved credentials and raw transport exception text are excluded.

Library callers may inject `Runner(provider_factory=...)`; a
`ChatCompletionsProvider(plan, transport=...)` accepts a public HTTPX asynchronous
transport and owns its cleanup. The deterministic tests use this boundary without
network calls. Both surfaces share mandatory local structured-result validation
and Provider-backed quality gates. vLLM profiles declare their per-surface
capabilities; see the explicit profile and conformance instructions below.

## Generate through Responses and retain private reasoning

An `openai` Provider defaults to `api = "responses"`. `ResponsesProvider` also
accepts the public HTTPX transport injection used by `ChatCompletionsProvider`.
The default factory supports Responses for OpenAI; generic compatible endpoints
and vLLM require a declared conformant profile before the factory enables that
surface. No live endpoint compatibility claim is made by the deterministic tests.

```toml
[providers.default]
type = "openai"
retain_reasoning = true # default; false suppresses persisted reasoning payloads

[model]
provider = "default"
name = "your-reasoning-model"
reasoning = { effort = "low", summary = "auto" }
```

`ReasoningControls(effort=..., summary=...)` is the equivalent typed Python value
on `ModelPlan` and `ProviderRequest`. Agent, Reviewer and Verifier model overrides
inherit these settings. Responses accepts both controls; Chat Completions accepts
`effort` and rejects summary requests before inference. Actual effort support
remains model-specific, so endpoint rejection produces an explicit typed error.
Reasoning settings and the Provider's retention policy are immutable Plan data.

Responses sends the complete accepted history as self-contained `input`, uses
`store = false`, and never sends `previous_response_id`. It maps token limits to
`max_output_tokens`, function calls/results to paired `call_id` items, and schemas
to `text.format`. Ordered text and function calls normalize to the same framework
Message and locally validated typed values as Chat Completions. Unsupported seed
sampling and provider-hosted Tools fail explicitly; hosted Tools cannot bypass the
framework's review-before-effect boundary.

`ProviderResponse.reasoning` contains framework-owned `ReasoningItem` values,
separate from its Message. Native model-call Events retain returned summaries,
exposed reasoning text and opaque encrypted continuity data by default, together
with presence, usage and native output item identifiers. The framework never
reconstructs hidden reasoning. Reasoning is excluded from Conversation, peer
Observations and OpenAI training exports. Reviewer calls use the same policy;
Verifier reasoning belongs to append-only Verification attempt Events.

Stateless reasoning models may require returned private items alongside accepted
Tool calls and results. Model Agents replay this data only for the same actor's
newly accepted exact Tool proposal, preserving its order among function calls.
Rejected proposal reasoning is never continued. `retain_reasoning = false` omits
all full reasoning and encrypted payloads from persisted Events; presence and
usage remain, while the accepted continuation exists only in memory during the
Trace. Direct Provider callers can supply an explicit `ReasoningContinuation`
paired with its accepted Message.

These semantics follow the official [Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create),
[function-calling guide](https://developers.openai.com/api/docs/guides/function-calling)
and [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning).

## Use explicit vLLM and compatible endpoint profiles

`vllm` connects to an independently managed external server. There is no core
vLLM engine dependency. Chat Completions is the default. Define a
`[providers.<id>.vllm_profile]` with the exact model, revision, vLLM version,
non-secret launch flags, parser names, tokenizer/chat-template identity, hardware
class, request-profile name, and per-surface capabilities. These values and typed
`[providers.<id>.vllm_options]` defaults are preserved in each immutable Run Plan.
The [pinned candidate and live-suite instructions](conformance/vllm/README.md)
provide a complete JSON configuration to translate into the same TOML fields.

**The bundled Qwen3 candidate is unverified; this repository currently makes no
real-server vLLM compatibility claim.** Ordinary tests are deterministic and do not
contact an inference service. Live checks require the dedicated
`python -m agentinstruct.vllm_conformance --allow-live ...` command, an explicit
server URL, actual hardware metadata, and a new report path. A recorded live pass
is required before declaring compatibility for that exact profile.

Python callers use `VllmProvider`, `VllmProfile`, `VllmSurface`, and `VllmOptions`.
`ProviderRequest.vllm_options` replaces the Provider Plan's option defaults for
that request. Native constraints use `VllmStructuredOutputs` with exactly one
mode: `json`, `choice`, `regex`, `grammar`, `json_object`, or `structural_tag`.
Typed whitespace/additional-property modifiers are separate. Reasoning controls
include `reasoning_effort`, integer `thinking_token_budget` (including `-1` for
unlimited), `include_reasoning`, and
`VllmChatTemplateKwargs(enable_thinking=...)`. Unknown fields, removed `guided_*`
fields, and arbitrary extra bodies/template kwargs are rejected. The template
kwargs currently cover Qwen-style `enable_thinking`; other model-specific keys
need an explicit typed addition and conformance case.

A surface defaults to text only. Declare each Tool-choice mode, response format,
native mode and reasoning control actually supported by that deployment.
`combinations` explicitly lists sorted pairs such as `reasoning+tools` or
`json_schema+reasoning`. Reasoning-capable profiles are treated conservatively as
reasoning-enabled unless their typed template option explicitly disables it.
Model overrides cannot borrow a different model's profile. Every used Agent,
Reviewer and Verifier is preflighted before participant inference. Use separate
Provider IDs when generation and judges need different native option defaults.
Pydantic structured results always undergo the same local validation as OpenAI.
Private returned reasoning stays in model-call Events under the existing retention
policy, and Chat Tool continuation sends accepted Messages without replaying
Responses-only reasoning items.

A vLLM Responses surface needs a separate `conformance = "passed"` declaration
and `report_digest`; a Chat pass does not enable it. Generic `openai-compatible`
Responses uses a smaller, distinct `CompatibleEndpointProfile` containing
`model`, `request_profile`, and `surfaces` of `CompatibleSurface`. In TOML those
live under `[providers.<id>.endpoint_profile]` and
`[providers.<id>.endpoint_profile.surfaces.responses]`. Its portable capability
fields are `response_formats`, `tool_choices`, `parallel_tool_calls`, `reasoning`,
`reasoning_controls`, and `combinations`, plus `conformance` and `report_digest`.
For Responses, the declaration must be passed and reference retained conformance
evidence; an unprofiled base URL cannot enable it. Generic endpoint declarations
do not accept vLLM parser/engine/native-option fields. Generic Chat retains its
existing portable behavior; extracted Chat reasoning requires the vLLM adapter.

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

### Failure evidence and cleanup

Lifecycle failures retain their stage, timestamp, safe exception/cause identities,
and available actor, Step, turn, proposal-attempt and revision context. Invalid
Agent return shapes fail before acceptance; Tool arguments and results require
strict JSON, including string object keys and finite numbers. No infrastructure
retry is performed.

External cancellation finalizes the Environment and closes every constructed
Provider, then seals and indexes the available failed Trace before propagating
`CancelledError`. Cleanup uses the configured Environment timeout for generation
resources and the Verifier timeout for verification resources. One failed or
timed-out cleanup does not skip remaining Providers. Reverification cancellation
appends an unverified attempt where storage permits, preserving earlier valid
quality decisions and all sealed generation files. When storage itself fails,
the framework preserves available evidence without publishing an unsealed Trace.

Credentials remain environment references in configuration. At execution time,
configured credential values are removed from recorded content, identifiers,
metadata keys, provenance and diagnostics; authentication headers are also
removed from diagnostic evidence, including quoted dictionary/JSON header values.
Proposals are redacted before review, and Tool results before output-schema
validation. Persistence rejects unsanitized Message Commits instead of changing
approved or validated values; later relay and Tool effects use those same Messages.
Authored non-secret Task/Seed fields remain intact. Source snapshots, their nested
directories, empty journals, terminal snapshots and verification sidecars are
synced before their published Run references.

`validate --json` returns `plans`, ordered per-record diagnostics, and valid/invalid
counts for a collection. A source error also appears as `source_error`; already
compiled records remain in the report. A single valid record additionally retains
the existing `plan` field. `TaskPackage.compile()` remains the one-record API and
rejects sources with zero or multiple records.

The [Seed sources example](examples/seed-sources/task.toml) combines CSV and JSON
files in a directory and validates each record against an offline JSON Schema:

```sh
uv run agentinstruct validate examples/seed-sources --json
uv run agentinstruct run examples/seed-sources --output runs --json
uv run python examples/seed-sources/run.py
```

Directory sources require `[seed] glob = "*.jsonl"` (recursive patterns such as
`**/*.jsonl` work too). Matching files are preflighted together, sorted by
Unicode-normalized path, and consumed in record order. `--seed` can override a
file or directory outside the package; directory overrides reuse the declared
glob. A file override works even when the package declares a directory.

CSV values remain strings in a flat mapping. Variable selectors address exact
headers, so `name = "full name"` and `case_id = "case.id"` are valid CSV bindings.
JSON and Python mapping inputs instead use validated dot paths through nested
mappings. Origins retain the input format and 1-based record position; CSV uses
the physical start line, including its header line. Wrong-width rows produce
invalid Traces; duplicate headers or unrecoverable CSV quoting fail the source.

Add `[seed] schema = "seed.schema.json"` for optional JSON Schema validation before
ID extraction, Variables, and rendering. The schema is preserved in the source
Task snapshot and Task digest. Schema references must stay within that document;
the validator uses an offline registry. Schema violations remain per-record
invalid Traces.

The `seeds=` argument accepts an iterable of JSON-compatible mappings or explicit
`Seed` objects on `Runner.run`, `generate`, `generate_sync`, `validate`, and
`compile`. It is mutually exclusive with `seed_path`. Mappings get a
`python:seeds` origin and a 1-based position, and follow the configured ID Variable
or content-hash rule. Explicit Seeds retain their logical ID and origin; their
digest is recomputed from their frozen data. Every declared Variable must still
resolve. Invalid yielded data is indexed without calling arbitrary object
representations; exceptions while acquiring or advancing the iterator fail the
Run and preserve earlier attempts.

Package references use exact path spelling, confined relative paths, portable
names, and no symbolic links. Agent and step directories must match their declared
participants and instruction/review files. Directory sources reject symbolic-link
directories and unsafe matched files before processing any record. Exports
preflight every selected source and reject destinations within its Run, Trace,
or Verification evidence, as well as symbolic/hard-link output aliases. Run output
directories also reject symbolic links. The standard macOS `/tmp`, `/var`, and
`/etc` aliases are accepted when they resolve to their corresponding `/private`
locations; links below them remain forbidden.

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

For a single-step dialogue, the target can return
`Message(role="assistant", content="Done.", control="complete")`. The completion
proposal takes effect only after that Message is accepted and persisted, producing
`terminated/completed`, even on the last allowed turn. A scripted target may use
`{ content = "Done.", control = "complete" }` in its `responses` array. Plain text
and script exhaustion never signal completion; exhaustion fails the Trace. Tasks with ordered Steps use reviewed `advance_step` and `complete_task` Tool
calls instead. The single-Agent Environment completes after its
one accepted Interaction.

Export persisted Run directories, Trace directories, or standalone `trace.json`
paths returned by `run`:

```sh
uv run agentinstruct export runs/<run-id>/traces/<trace-id> \
  --format openai --status unverified --output dialogue.jsonl
```

`--format native` exports complete Trace snapshots. Both formats select only
`accepted` by default; repeat `--status` to explicitly select other statuses.
`--run-id`, `--trace-id`, and `--seed-id` filter identities; each is repeatable,
values within a filter are alternatives, and different filters intersect. Python
exports accept `run_ids`, `trace_ids`, and `seed_ids` sets. Input order and each
Run index order are preserved. Selection uses current persisted Verification
status, not historical Run counts; `--verification` explicitly selects a valid
attempt. Empty selections still protect every input Run and its evidence from
being overwritten. Tool arguments remain structured JSON in both formats; only
Provider wire requests stringify them.

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

For custom Review, select an [explicit class reference](#load-custom-components)
or pass `Runner(reviewer_factory=...)`. The factory receives a
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
Model Reviewers use `type = "model"` with the structured quality contract below.

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
identity and available source digest. Explicit `module:function` references are
supported through `type = "function"`; the example demonstrates injected factories.

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

For domain-specific code or a judge-shaped extension, select an
[explicit class reference](#load-custom-components), or use `type = "custom"`
without `[verifier.checks]` and provide `Runner(verifier_factory=...)`. Each
factory receives the immutable `VerifierPlan` and constructs a fresh `Verifier`
implementing `async verify(trace: TraceSnapshot) -> VerificationResult`. Return
`VerificationResult(criteria={"has_reply": True, "completed": False}, feedback="...")`.
The result may also contain a sequence of `(criterion_id, bool)` pairs. Missing,
duplicate, unknown, and non-Boolean verdicts are errors. Factory exceptions,
verification exceptions, timeout, and malformed results record an **unverified**
attempt with error details and no invented false verdicts. Model Verifiers use
`type = "model"` with the structured quality contract below.

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

## Inspect recorded Runs and Traces

Inspection reads a recorded Run directory, Trace directory, or standalone Trace
snapshot. It needs no original Task Package, custom component imports, credentials,
or running model service.

```bash
uv run agentinstruct inspect runs/RUN_ID
uv run agentinstruct inspect runs/RUN_ID --json
uv run agentinstruct inspect runs/RUN_ID --trace 1 --view conversation
uv run agentinstruct inspect runs/RUN_ID --trace 1 --view participant --participant assistant
uv run agentinstruct inspect runs/RUN_ID/traces/TRACE_ID --view reasoning --json
uv run agentinstruct inspect runs/RUN_ID --tui
```

Run summaries retain the ordered Trace references and all five status counts.
`counts` uses each Trace's current decision, including appended Verification
attempts; `recorded_index_counts` and `manifest` preserve the historical Run
evidence. A failed latest Verification can coexist with an earlier selected valid
decision. Both are shown in the Trace summary. Relative index paths allow a whole
Run directory to be moved; escaping paths and mismatched identities are rejected.

The terminal UI uses line commands and requires no terminal framework:

- `trace N` selects a Trace using its one-based position; `next` and `previous`
  move between Traces; `run` returns to the collection summary.
- `summary`, `conversation`, `tools`, `reviews`, `verification`, `provenance`,
  `failures`, `artifacts`, and `reasoning` select operator views.
- `participant ID` projects only accepted shared Messages and that participant's
  own private Tool exchanges, with roles relative to that participant.
- `more`, `back`, and `page N` navigate long views; `help` lists commands; `quit`,
  EOF, or Ctrl-C ends inspection.

Conversation views label actors, visibility, turns, Task Step boundaries, and
review-exhausted Messages. Operator views include all actor-private evidence and
rejected proposals. Participant views contain accepted Messages only and enforce
Tool ownership. Reasoning views include both
generation model calls and model calls inside Verification attempts, showing
declared retention policies, presence, and suppression without inventing missing
text. Terminal control characters in recorded text are escaped. Artifact views
list persisted regular files and sizes; standalone snapshots without an artifact
directory have an empty listing.

The same read-only model is available in Python. Library Trace positions are
zero-based:

```python
from agentinstruct import Inspector, load_run

recorded = load_run("runs/RUN_ID")
for reference in recorded.traces:
    print(reference.path, reference.snapshot.status, reference.recorded_status)

inspector = Inspector("runs/RUN_ID")
summary = inspector.summary()
projection = inspector.view("participant", trace_index=0, participant="assistant")
print(inspector.render("conversation", trace_index=0))
```

Inspection never rewrites generation files, appends Verification, resumes a Run,
or invokes components. Open a new Inspector to read subsequently appended attempts.

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

Schema version `"1"` supports built-in `single` and `dialogue` Environments plus
[explicit custom Environments](#load-custom-components), exactly one Target Agent,
and the `local` Runtime. [Seed sources](#run-a-seed-collection) include JSON
objects/arrays, JSONL, CSV and ordered directory sources; Python callers may also
supply iterable Seeds. Every Agent requires `agents/<id>/instruction.md`. Unknown
configuration fields and unsupported component selections fail validation. Task
Steps are optional; a Task without declared steps omits the `steps/` directory.

`[variables]` maps template aliases to dot paths through nested JSON mappings.
Array indexing and empty path segments are unsupported. Every selector must
resolve, and instruction templates use strict, sandboxed Jinja. Templates may
interpolate JSON values; Python methods and other runtime attributes are rejected
(use Jinja filters such as `name | upper`). Iterator filters produce data lists,
and the nondeterministic `random` filter is unavailable. A `[seed]`
`id_variable` names a declared alias containing a nonempty string or integer;
otherwise the Seed ID is its canonical content hash.

`[model]` supplies the provider identifier, model name, and optional `temperature`
and `max_tokens`, plus typed `reasoning` settings; an Agent's
`[agents.<id>.model]` may override those fields.
Provider declarations support `openai`, `openai-compatible`, and `vllm` identities.
The runtime implements Responses and Chat Completions for `openai` and Chat
Completions for `openai-compatible`, plus explicitly declared compatible Responses
and vLLM surfaces as described above.
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

### Use structured quality gates

A model Reviewer uses the same pre-acceptance boundary as a custom Reviewer;
set `type = "model"` in `[agents.<id>.reviewer]` and provide the existing
`reviewer.md` and `rubric.toml`. Optional `[agents.<id>.reviewer.model]` fields
inherit that Agent's resolved model settings. A model Verifier uses
`[verifier] type = "model"`, `verifier/rubric.toml`, and a required
`verifier/instruction.md`; `[verifier.model]` inherits Task model defaults.
Instructions are strict templates rendered from each Seed before generation.
Both `responses` and `chat_completions` support these flows when the selected
Provider surface declares the required structured-output capabilities.

Both model judges receive a Pydantic `QualityDecision` with a list of
`{"id": "criterion-id", "passed": true}` entries and text `feedback`. The
framework requires every active Criterion exactly once, with actual Booleans,
and derives the weighted score. Reviewer step criteria append normally;
Verification uses its own Rubric. Invalid output fails Review before any Message
commit or Tool effect, or leaves final Verification unverified. Valid negative
verdicts follow normal revision or rejection policy.

Run the [offline structured-quality example](examples/structured-quality/run.py):

```bash
uv run python examples/structured-quality/run.py
```

Its fake HTTP transport makes no model calls. For live inference, configure a
real endpoint/model and use `Runner()` without that transport factory.

Python Provider callers may author their own result class:

```python
from pydantic import BaseModel, ConfigDict
from agentinstruct import Message, ProviderRequest, compile_structured_output


class Assessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    feedback: str | None


snapshot = compile_structured_output(Assessment)
# snapshot is immutable JSON data, with name, schema, strictness, description,
# qualified type name, and a canonical fingerprint. It contains no class object.
request = ProviderRequest(
    "your-model",
    (Message("user", "Assess the response."),),
    structured_output=Assessment,
)
response = await provider.generate(request)
assert isinstance(response.parsed, Assessment)
```

Alternatively pass `JsonSchemaSpec("assessment", schema_dict, strict=True)`
or a compiled `StructuredOutputPlan`; `.parsed` then contains immutable JSON
values. Mutable schema dictionaries and arrays are detached when compiled.
Pydantic schemas use validation aliases; strict wire normalization requires all
fields (nullable values remain allowed) and forbids undeclared properties.
Explicit JSON Schema contracts are preserved: incompatible strict schemas fail
preflight instead of having their constraints removed.

Both OpenAI surfaces preflight their documented strict schema subset, including
local recursive references. Remote schema references are unsupported and never
fetched. Local JSON, schema, format, and strict Pydantic validation remain mandatory
regardless of server constrained decoding. Duplicate object keys and nonfinite
numbers are invalid JSON; numeric/string Boolean substitutes and extra fields
fail the schema. `ProviderError.kind` distinguishes `refusal`, `incomplete`,
`invalid_json`, `schema_mismatch`, and `unsupported_schema`; the last three use
`StructuredOutputValidationError`. There are no automatic retries. The schema
rules follow [OpenAI's structured-output guide](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Pydantic strict JSON validation](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/).

Verifier calls, typed results or failures, usage, and the selected Provider Plan
are persisted in the immutable Verification attempt sidecar. Reverification
opens and closes fresh Provider resources and never changes generation files.
`reverify(path, package=TaskPackage.load("new-policy"))` and CLI
`reverify --package new-policy` compile the policy against the persisted Seed,
including when the new package's seed file differs. The attempt snapshots its
actual endpoint/API/model/schema and rendered instruction. These rules also
apply to standalone native snapshots; later judge errors preserve the latest
valid decision's export eligibility.
