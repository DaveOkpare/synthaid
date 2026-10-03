# Library architecture audit

Type: exploration
Status: resolved
Date: 2026-10-03
Scope: current working tree, including the user's uncommitted refactor

The exploration and all five implementation slices are complete. See the
[implemented sequence](spec.md), [final report](implementation.md) and
[measured inventories](metrics.json). The audit findings below retain the
7,401-line starting baseline and historical design discussion; current interfaces
follow [ADR-0025](../../docs/adr/0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md).

| Slice | Result |
| --- | --- |
| [01 — Task, Environment and Runner](issues/01-task-environment-runner.md#answer) | resolved |
| [02 — Judge and Tool](issues/02-judge-and-tool.md#answer) | resolved |
| [03 — Agent and model client](issues/03-agent-and-model-client.md#answer) | resolved |
| [04 — Episode recording](issues/04-episode-recording.md#answer) | resolved |
| [05 — Optional adapters and release](issues/05-optional-adapters-and-release.md#answer) | resolved |
| [06 — Follow-up invariants review](issues/06-final-review-invariants.md#answer) | resolved |

The user clarified that Taskset is simply a list of Tasks. Each Task carries
Agent definitions and quality settings; later refinements put Tools and reviewers
on each Agent definition and the verifier on Task.
Environment.setup(task) initializes the participants and critics; run() executes
the conversation and passes the accepted Episode history to the final judge.
[ADR-0014](../../docs/adr/0014-use-task-lists-and-task-owned-run-settings.md),
[ADR-0015](../../docs/adr/0015-separate-environment-setup-and-run.md) and the revised
plan take precedence over the original ownership recommendations below. The
measurements and findings still describe the unchanged source baseline.

The user further narrowed the core to Task, Runner, Environment, Agent, Episode,
Tools and Judge, with few methods and functions below 20 lines. The rewritten
[plan](spec.md) and [ADR-0016](../../docs/adr/0016-build-seven-directly-usable-generation-modules.md)
replace the earlier keep-every-module recommendations and define explicit deletion.

The reviewer refinement puts optional reviewer settings on each Agent definition,
an optional verifier on Task, and defines Episode as the independent output of
one Environment run. See [ADR-0017](../../docs/adr/0017-use-agent-reviewers-task-verifiers-and-independent-episodes.md).

Runner takes output_dir and chooses a unique Episode path for every execution.
Episode records during execution.
See [ADR-0018](../../docs/adr/0018-runner-owns-the-output-directory.md).

Task-owned Episodes span segments. Ordered segments reveal
fresh instructions while retaining one accepted Conversation and private Tool
history. Runner attaches a fresh Task.episode; Environment.setup(task) and run()
execute into it, with final judgment after task-wide sealing. The loader keeps
authored phases within one Task, replacing separate-record expansion. See
[ADR-0019](../../docs/adr/0019-task-owned-episodes-span-segments.md).

The automatic Episode refinement makes Task construction create its own empty
Episode and unique ID automatically. Runner opens recording using that existing
ID rather than replacing the Episode. See
[ADR-0020](../../docs/adr/0020-create-an-identified-episode-with-each-task.md).
The plan now proposes constructor-bound Environment(task)/run() and fresh Task
instances for independent samples; removing public setup and changing completed
Task reuse have not been explicitly settled by the user.

The Tool refinement places tools on each Agent definition, alongside its model,
instruction and optional reviewer. Task has no tools field or shared Tool pool.
Environment assembles the per-Agent declarations; call resolution uses only the
calling Agent's assignments. Existing file catalogs resolve into those definitions.
See [ADR-0021](../../docs/adr/0021-declare-tools-on-each-agent.md).

The spec now makes Runner.client initialization and ownership explicit: the
application owns an async model client for the whole batch, and execution modules
borrow it. The direct example initializes the candidate SDK client and closes it
in an outer async scope. Judge has one reusable constructor/evaluate interface;
the example supplies one instance as both Agent.reviewer and Task.verifier.
Invocation history, verdict evidence and revisions stay with their actual owners.

The latest refinement uses Agent(model, instruction, tools, reviewer) directly.
Task.agents holds configured Agent instances; Environment
uses those instances, with execution state in Episode and local calls. A rejected draft and the
reviewer's guidance reach Agent.generate through temporary private history, and
the Agent authors a replacement for review before acceptance/effects. See
[ADR-0022](../../docs/adr/0022-construct-agent-definitions-and-revise-from-review.md)
for the feedback loop and [ADR-0023](../../docs/adr/0023-use-agent-directly-and-keep-execution-state-local.md)
for removal of the definition/runtime split.

Task roles are now limited to the required assistant target and an optional user
Agent. Task.agents keeps the definitions under those two supported keys, with
assistant required and user optional. There are no separate role fields or target
selection. See
[ADR-0024](../../docs/adr/0024-use-required-assistant-and-optional-user-task-roles.md).

## Assessment

The intended ownership is already sensible: Runner iterates tasks; Environment
schedules a complete conversation; Agent owns acceptance and effects; Episode
records evidence. The remaining problem is incomplete encapsulation of those
owners. The optional task-file adapter assembles partly initialized objects,
recording understands authoring details, and cleanup knows private details of
model verification. Long methods concentrate those overlapping responsibilities.

Agent.turn, Environment.run, Provider.generate and Inspector already provide
useful depth. Preserve their leverage and improve their implementations. Creating
more classes, moving the same code between files, or reducing method lengths by
adding forwarding helpers would not resolve the underlying maintenance cost.

## Measured baseline

An AST inventory of all shipped Python files found:

| Measure | Current working tree |
| --- | ---: |
| Python files | 28 |
| Physical source lines | 7,401 |
| Class definitions | 94 |
| Function/method definitions | 287 |
| Definitions over 20 lines | 57 |
| Top-level exports | 49 |

Function counts include nested functions and Protocol stubs. Length is inclusive
from the `def` line to the AST end line, including signatures, comments and blank
lines, excluding decorators. These are navigation signals, not measures of depth.
Twenty-one classes are private wire-validation models in providers/responses;
their number alone does not establish overengineering.

The five largest files contain 4,012 lines, about 54% of shipped Python. This
makes focused changes more useful than a repository-wide style rewrite.

| File | Lines | Longest definition | Span |
| --- | ---: | --- | ---: |
| task_package.py | 1,171 | TaskPackage.compile_records | 178 |
| execution.py | 962 | Agent.generate | 129 |
| providers.py | 808 | ProviderRequest.__post_init__ | 107 |
| inspection.py | 543 | Inspector.view | 102 |
| store.py | 528 | Episode.__init__ | 90 |

Other prominent definitions: TaskPackage.load 163; reverify 146;
preflight_structured_output 142; Agent.turn 122; Responses normalize_response
118; QualityCall.evaluate 101; OpenAIProvider.generate 100; vllm_server 81;
Agent._execute_tool 77; Episode.register_agents 77; Agent._review 76;
InspectionSession.execute 53. Runner has two methods and 23 total lines.

## Findings, in recommended order

### 1. Agent acceptance mixes independent implementation concerns

Evidence: [Agent.generate](../../src/agentinstruct/execution.py#L147),
[Agent._review](../../src/agentinstruct/execution.py#L426),
[Agent.turn](../../src/agentinstruct/execution.py#L503),
[Agent._execute_tool](../../src/agentinstruct/execution.py#L626).

`generate` handles a private callback, scripted responses, request projection,
reasoning continuation, inference, evidence and response checks. `turn` handles
Episode attachment, Reviewer recording, proposal queues, per-message revisions,
commit construction, accepted reasoning and Tool continuation. The constructor
has 16 parameters after `self`, mixing generation selection and acceptance policy.

The external seam is useful: a custom Agent overrides generate(observation) while
turn(episode) still enforces Review and effects. Keep that seam. Separate cohesive
private operations for request construction, accepting one Message, and Tool
continuation. Counters and pending reasoning should stay with their actual Agent;
do not create a TurnSession, Interaction replacement, or generic state machine.

Multi-message proposals have a concrete use: PrefixedAgent in test_lean_agents.py
adds a prefix before a model proposal. The queue and independent revision budgets
cannot be deleted as hypothetical behavior. Likewise, accepted reasoning must
survive that wrapping while rejected reasoning never becomes continuation.

The private `_proposal` branch has no current example/task user found; all shipped
custom Agent examples subclass Agent. Its adapter path also accepts an arbitrary
generate-only object. Candidate retirement: require actual Agent subclasses for
task-selected custom Agents, then remove `_proposal` and its forwarding path.
That changes an extension contract and should be recorded explicitly.

### 2. The Tool implementation is split across the wrong places

Evidence: [tools.py](../../src/agentinstruct/tools.py),
[Agent._execute_tool](../../src/agentinstruct/execution.py#L626).

tools.py is only 117 lines. FunctionTool earns its small wrapper: callers supply
an async function and the declaration data needed by real model requests. Tool
is a real seam with function and custom adapters. Those types are not the main
source of bloat.

The burden is the 77-line Agent method: assignment lookup, input validation,
execution, result conversion, exception policy, diagnostic evidence and result
commit. Consolidate call/result mechanics in tools.py; Agent should own the
ordering of approval, durable intent, started/error Events and durable result.
Keep Tool.call(args) as the public contract; ordinary closures supply domain data.

Agent validates a result with TypeAdapter, then tool_result_content validates it
again. This is a concrete duplication candidate, but the first validation rejects
arbitrary Python values before the diagnostics serializer can convert them. A
replacement must preserve that order, redaction and schema checking of the
Agent-visible result. Removing the first check alone changes behavior.

### 3. Episode exposes storage and authoring details to execution

Evidence: [Episode.__init__](../../src/agentinstruct/store.py#L101),
[Episode.register_agents](../../src/agentinstruct/store.py#L192),
[Environment._execute/_failed](../../src/agentinstruct/execution.py#L773),
[LocalRunStore.publish_episode](../../src/agentinstruct/store.py#L424).

Episode's constructor infers an authored record from four dictionary keys, parses
task/Seed evidence through the Seed reader, builds provenance and creates durable
files. register_agents knows Agent generation options, Reviewer layout, Tool
declarations and Provider attributes. It is called at Environment startup and
again on every Agent turn, even when declarations are already registered.

Environment writes Episode._stage and _cancelled; LocalRunStore reads
_persistence_error. The public conversation/events lists can also be mutated
without crossing the durable append interface. These facts enlarge the interface
that callers must know despite the apparently small commit/event methods.

Deepen the existing Episode rather than introduce another recorder: localize
accepted-history projection, commit metadata and sealing; keep execution stage
and cancellation with Environment; expose storage failure through an explicit
result or property. Pass authored provenance explicitly instead of recognizing
application payloads by their key names. Separate metadata projection from
filesystem appends using ordinary mappings, without a new Plan/context model.

Keep registration support for Agents used by custom conversations. Register
declarations once per Episode/Agent rather than repeatedly harvesting Provider
metadata. Keep the existing historical run_plan field on disk.

### 4. Environment scheduling is simple; cleanup ownership is tangled

Evidence: [Environment.run](../../src/agentinstruct/execution.py#L746),
[Environment._providers/_resources/aclose](../../src/agentinstruct/execution.py#L824),
[Environment._record_verifier_close](../../src/agentinstruct/execution.py#L858),
[ModelVerifier.aclose](../../src/agentinstruct/verification.py#L114).

The single-Agent and dialogue conversation loops are already small, ordinary
Python. Environment.run is ten lines. They are not a justification for a new
scheduling abstraction or another Runner refactor.

Cleanup reaches through reviewer.call.provider and verifier.call.provider,
tracks object identities, and reads ModelVerifier._provider_close_attempted to
infer whether another object already closed a shared dependency. This exists
because resource ownership is overlapping, not because cleanup needs more phases.

Choose one owner for each Provider lifetime and make borrowing explicit. A
framework model Verifier should borrow a Provider while Environment owns it;
standalone package reverification should close the dependencies it constructs.
Custom closers and shared Providers require an explicit ownership convention.
Do not simplify by assuming every custom Provider close is idempotent.

This proposal changes the current inferred ownership of custom objects exposing
call.provider. Tests at test_lean_runner.py:988–1074 deliberately cover a
non-idempotent Provider and verifier failures before/after Provider cleanup.
Preserve observable close-once, bounded cleanup and primary-error behavior while
migrating that convention. Record the contract change in an ADR before coding.

### 5. TaskPackage is a large optional adapter with too much runtime knowledge

Evidence: [TaskPackage.load](../../src/agentinstruct/task_package.py#L256),
[compile_records](../../src/agentinstruct/task_package.py#L464),
[create_environment/_bind_agent](../../src/agentinstruct/task_package.py#L812),
[_custom_agent](../../src/agentinstruct/task_package.py#L949).

Loading combines layout checks, reference resolution, templates, rubrics and
schemas. Compilation combines identity recovery, validation, rendering,
model defaults, phase expansion and preparation-error records. Runtime binding
creates an empty Environment, inserts Agents, mutates their dependencies and
review policy, copies attributes into custom Agents, and sets private diagnostics.

There is also ordinary duplication: phase files are read before a loader reads
them again; singleton loops surround one file; compile_records resolves the ID
selector before _variables traverses the same data; ProviderRequest checks Tool
schemas again on every generated request after authoring already checked them.
Immutable declaration validation can be reused, but custom mutable declarations
must not silently become cached without a documented contract.

Keep TaskPackage as a deep authoring interface and preserve current task files.
Use cohesive private functions returning ordinary records: validate source,
render one Seed, expand phases, construct actual Agents. Bind dependencies through
constructors rather than post-construction patching. Introduce a separate private
adapter module only if it permits core code to shed authoring knowledge; a file
split alone produces no reduction.

components.py is already limited to explicit references and has real task users.
Retain reference lookup and useful early errors. Narrow its supported contracts
alongside Agent/Environment construction; do not add registries or plugin discovery.

### 6. Shared mechanics depend on domain-specific modules

Evidence: providers.py, responses.py and structured.py import parse_json from
seeds.py; providers.py and structured.py import schema_validator from tools.py.
Agent._observation, Agent.generate, Inspector.view and export_openai each
implement participant visibility or role projection.

Put strict JSON parsing beside the JSON utilities in data.py. Place reusable
offline schema mechanics with the schema implementation and remove its reverse
dependency on Tools. Preserve error labels and offline reference resolution.

Share participant visibility and role conversion as separate pure operations
over accepted Message Commits in traces.py. Runtime Observation currently exposes
stored Message roles; only model-request projection remaps them. Inspector and
export remap participant roles too. A combined helper that normalizes every
Observation would inadvertently change the custom Agent contract.

### 7. Model-call evidence is duplicated; wire codecs are genuinely different

Evidence: [Agent.generate](../../src/agentinstruct/execution.py#L147),
[QualityCall.evaluate](../../src/agentinstruct/quality_provider.py#L53),
[OpenAIProvider.generate](../../src/agentinstruct/providers.py#L468),
[reverify](../../src/agentinstruct/verification.py#L154).

response_evidence already shares successful-response serialization. Participants
and quality calls still duplicate call execution, refusal/incomplete checks and
Event construction. Agent.turn reassigns Reviewer recording; reverify temporarily
replaces and restores a QualityCall callback. This means the recorder's lifetime
is implicit in another object's mutable configuration.

Use one private model-call/evidence operation with a sink scoped to the invocation;
keep judgment decoding and acceptance policy separate. Make the built-in quality
recording path explicit without forcing custom Reviewers to implement model
inference. Do not turn this into a provider facade or inference middleware stack.

Keep separate Responses and Chat Completions codecs, local structured-output
checks and typed wire models. Those adapters differ in Tool shape, reasoning
continuation, output items and inference support. Shared transport is already
the accepted design. Large codec/schema methods need cohesive parsing/checking
operations, not one generic configurable codec.

### 8. Inspection and optional interfaces are a later readability pass

Evidence: inspection.py's view/render/reasoning functions,
[InspectionSession.execute](../../src/agentinstruct/ui/terminal.py#L42),
[vllm_server](../../src/agentinstruct/integrations/vllm/serve.py#L31).

TUI isolation already succeeded; the remaining navigation method is a 53-line
command parser. The 81-line launcher combines option checks, launch, readiness,
signal restoration and cleanup behind a useful context manager. Both are good
candidates for a few cohesive private operations, with the existing outer
interfaces unchanged.

Inspection's larger cost is its presentation feature set. Its read-only Inspector
interface is already useful. Reuse participant projection and summary data first;
preserve terminal escaping. Deleting reasoning/artifact views or replacing human
rendering with raw JSON is a product change, not a behavior-preserving refactor.
The [earlier inspection audit](../lean-core-refactor/inspection-audit.md) explains
those tradeoffs; its old test/module references need updating before use.

## Original file disposition (superseded)

This table records the original conservative audit recommendation. The current
deletion/absorption plan is in [the revised specification](spec.md#current-files-explicit-disposition).

| File | Recommendation |
| --- | --- |
| __init__.py | Keep canonical exports; remove a name only with a concrete retirement. |
| runner.py | Keep current loop. |
| execution.py | Deepen Agent; simplify Environment recording/cleanup coupling. |
| tools.py | Keep Tool/FunctionTool; own call/result mechanics here. |
| store.py | Deepen Episode; distinguish recording from authoring interpretation. |
| traces.py | Keep immutable data records; share accepted-history projection here. |
| task_package.py | Simplify preparation and construct fully configured actual owners. |
| components.py | Keep adapter-only explicit lookup; narrow overlapping contracts. |
| providers.py | Keep transport; simplify request validation and call/evidence mechanics. |
| responses.py | Keep separate wire codec; simplify cohesive encoding/decoding operations. |
| structured.py | Keep local schema guarantees; separate traversal, node checks and limits. |
| quality_provider.py | Share model-call mechanics; remove implicit sink lifetime. |
| review.py | Keep distinct per-message Review seam and weighted verdict result. |
| verification.py | Keep independent final Verification; simplify attempt/cleanup mechanics. |
| quality.py | Keep small, shared scoring implementation. |
| data.py | Keep JSON projection/freezing; add neutral strict JSON parsing. |
| seeds.py | Keep supported formats and origin evidence; remove duplicate projection carefully. |
| failures.py | Keep redaction and cancellation-aware cleanup; simplify only demonstrated duplication. |
| provider_errors.py | Keep safe classified failures; no evidence for a large cut. |
| paths.py | Keep confined/portable path operations. |
| export.py | Share participant projection and common iteration; preserve source protection. |
| inspection.py | Reuse projections/summary; simplify formatting after the core. |
| cli.py | Keep current thin command selection; revisit only if interfaces change. |
| ui/terminal.py | Simplify command categories with private functions, preserving navigation. |
| integrations/vllm/serve.py | Isolate readiness/launch operations; preserve process ownership. |
| integrations/__init__.py | Keep namespace marker. |
| integrations/vllm/__init__.py | Keep namespace marker. |
| ui/__init__.py | Keep namespace marker. |

## Verification and limits

- Read all 28 source files, current examples, relevant tests, CONTEXT.md and ADRs.
- Full offline suite: **355 passed in 40.02s**.
- Ruff lint passes; Ruff format check: **105 files already formatted**.
- Strict mypy: **48 source files, no issues**.
- The first pytest invocation lacked .venv/bin in PATH and had 25 command-not-found
  failures. Repeating with the installed console command on PATH passed fully;
  these were invocation errors, not identified application regressions.
- No production code or tests were changed. Subsequent design updates affect only
  the audit/specification, domain glossary and ADRs. No live inference, packaging
  build or performance benchmark was needed for this audit.

This is an architecture audit, not proof that every private function or external
extension is unused. Deletion candidates identify current evidence and explicit
contract changes. No future source-line saving is claimed as measured.
