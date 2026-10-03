# Seven-module implementation report

Type: implementation report
Status: resolved
Date: 2026-10-03
Scope: execute [the accepted specification](spec.md) from the user's uncommitted working tree

All five implementation slices are complete. The root exports only Task, Runner,
Environment, Agent, Episode, Tool and Judge. The core occupies seven modules plus
its import file; the optional task-file adapter, CLI, inspection, TUI and vLLM
launcher remain available. [ADR-0025](../../docs/adr/0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
records the implemented constructor/run boundary, one-Task-per-execution policy
and SDK adoption. [Migration notes](../../docs/migration-seven-modules.md) document
retired Python interfaces and supported authoring syntax.

## Implemented ownership

Task constructs its Episode and UUID immediately without files or inference. Its
required assistant and optional user are configured Agent instances. Input and
ordered segment declarations are ordinary immutable data. Runner opens that same
Episode at output_dir / episode.id and constructs one Environment per Task.
Environment.run returns None, prepares explicitly owned resources inside the
Task deadline, activates instructions in order, preserves accepted/private history,
seals once and invokes the optional final Judge. Failed Tasks cannot reset output.
Structural custom Environments retain the constructor/run extension point.

Agent combines stable settings and generation behavior. Invocation-local role,
client and instruction inputs permit concurrent reuse without rebinding settings.
Per-message revision counters, drafts and validated feedback stay local. Accepted
messages alone enter Episode.messages. Review precedes acceptance; durable,
fsynced Tool intent precedes capability execution. Each Agent advertises/resolves
only its own Tools; shared capabilities require an explicit reference on both.
Private results and exact accepted reasoning stay with the caller across segments.
Rejected drafts, peer-private Tools and grading inputs stay outside training exports.

Judge has one constructor/evaluate interface for callable or model evaluation.
Agent owns replacement budgets; Episode owns final verification records. Rubrics
require exact Boolean criterion identities and finite weighted scores. Malformed,
failed or timed-out judging remains evidence, never implicit approval. A reusable
Judge can serve review and final verification across independent Tasks.

Episode is the sole history/persistence representation. It exposes immutable
views, records during execution, publishes generation exclusively once and appends
verification sidecars. Storage failures stop effects. Opening failures preserve
identity and in-memory error evidence without overwriting existing output.
Cancellation and publication failures preserve primary failures. Resource cleanup
is bounded and shielded; cleanup TimeoutError fails execution rather than being
misclassified as a generation deadline. Historical Trace JSON preserves stored
identities, targets and timestamps. Standalone files use filename.verification/.

Applications own model clients around whole batches. Core calls borrow them and
force disabled SDK retries, streaming and server-side storage. Agent/Judge use the
same mature client path with distinct acceptance semantics. Both Chat Completions
and Responses wire values are strictly revalidated using the SDK's own models;
local JSON/schema, privacy and Tool rules remain enforced. No Provider hierarchy,
framework wire-model copies, registry, Run store or forwarding aliases remain.

The optional loader performs inert validation/rendering and emits the same Task
objects as direct Python callers. It retains JSON, JSONL, CSV, directories and
Python iterables, strict templates, record origins and exact source-text digests.
Invalid individual records remain distinct from unreliable source boundaries.
Authored phases become ordered segments within one Task. Custom references are
syntax-checked during compilation and imported only during construction. Symlink,
portable-name and layout checks apply to base and phase files. CLI, Inspector and
TUI read Episodes directly; the launcher retains process/signal ownership.

## Measured size

The baseline is the source present when this request began, including the user's
uncommitted refactor. It is not Git HEAD. A read-only copy was captured under
/private/tmp/agentinstruct-audit-baseline-20261003. Counts include every recursive
shipped .py file, including package markers; exclude tests, examples, documents,
cache files and external dependency implementations. Physical lines include blank
lines. AST counts include nested definitions and Protocol stubs. Function spans
start at def, include signatures/comments/blanks and exclude decorators.
[metrics.json](metrics.json) contains both per-file inventories and private names.

| Measure | Baseline | Implemented | Change |
| --- | ---: | ---: | ---: |
| Shipped Python files | 28 | 17 | -11 |
| Physical source lines | 7,401 | 4,293 | -3,108 (42.0%) |
| Classes | 94 | 26 | -68 |
| Function/method definitions | 287 | 295 | +8 |
| Private non-dunder function/method definitions | 109 | 214 | +105 |
| Root exports | 49 | 7 | -42 |
| Definitions at least 20 inclusive lines | 68 | 0 | -68 |
| Longest definition | 178 | 19 | -159 |

The baseline grouping follows the specification's destination responsibility:
components/task_package/seeds and the existing CLI/inspection/TUI/launcher are
optional; remaining source is core. Final core includes __init__.py. Final optional
includes its four namespace markers.

| Group | Files before / after | Lines before / after | Classes before / after | Definitions before / after | Private before / after |
| --- | ---: | ---: | ---: | ---: | ---: |
| Core | 18 / 8 | 4,616 / 2,367 | 80 / 19 | 171 / 161 | 36 / 100 |
| Optional | 10 / 9 | 2,785 / 1,926 | 14 / 7 | 116 / 134 | 73 / 114 |

Private helper count increased. Fully qualified file/scope identities show 204
added and 99 removed private definitions, net +105; moving a name across modules
counts as removal/addition. This is not a claim of fewer functions or a direct
measure of conceptual depth. The strict line limit required cohesive extraction
of parsing, schema traversal, persistence and source-boundary operations. No
forwarding modules or parallel runtime owners were added. Remaining largest
files are Agent (960 lines) and the optional loader (929 lines); their size is
reported rather than hidden behind private subsystem directories.

| Current file | Lines | Classes | Definitions | Private non-dunder |
| --- | ---: | ---: | ---: | ---: |
| __init__.py | 11 | 0 | 0 | 0 |
| adapters/__init__.py | 1 | 0 | 0 | 0 |
| adapters/task_files.py | 929 | 4 | 65 | 59 |
| agent.py | 960 | 3 | 59 | 54 |
| cli.py | 385 | 0 | 26 | 24 |
| environment.py | 196 | 2 | 16 | 14 |
| episode.py | 739 | 5 | 57 | 20 |
| inspection.py | 287 | 1 | 19 | 14 |
| integrations/__init__.py | 1 | 0 | 0 | 0 |
| integrations/vllm/__init__.py | 1 | 0 | 0 | 0 |
| integrations/vllm/serve.py | 199 | 1 | 15 | 12 |
| judge.py | 228 | 5 | 15 | 8 |
| runner.py | 47 | 1 | 3 | 1 |
| task.py | 91 | 1 | 4 | 3 |
| tools.py | 95 | 2 | 7 | 0 |
| ui/__init__.py | 1 | 0 | 0 | 0 |
| ui/terminal.py | 122 | 1 | 9 | 5 |

## Deletion versus consolidation

Eighteen baseline modules were deleted: components, data, execution, export,
failures, paths, provider_errors, providers, quality, quality_provider, responses,
review, seeds, store, structured, task_package, traces and verification.
Those paths contained 6,035 lines. Seven new paths contain 3,144 lines, including
the new adapter namespace marker. Retained files shrank from 1,366 to 1,149 lines.
Thus 6,035 deleted-path lines are not a net saving: replacement/consolidation adds
3,144, retained files remove 217, and the measured net removal is 3,108.

Necessary parsing, validation, evidence and projection behavior moved to its real
owner. Genuine removal includes Provider request/response/wire-copy classes,
separate review/final-judgment families, live/snapshot/reference conversions,
LocalRunStore, Seed/component registries and separate Agent-definition/runtime
assembly. The mature SDK adds an external dependency; its code is excluded from
these local package measurements. Earlier deletions already present at the start
of this request, including Plan/control/compatibility modules, are not credited.

The optional total falls 859 lines (30.8%). Loader consolidation replaces 1,663
lines across task_package/components/seeds with 929 lines. Inspector falls from
543 to 287; TUI from 123 to 122. CLI grows from 290 to 385 because it now constructs
core Tasks, owns application client scopes and publishes its manifest directly.
The launcher grows from 163 to 199 while retaining process cleanup and meeting the
same function limit. These are aggregate simplification results, not a claim that
every retained optional file became shorter.

## Dependency change

Add and pin openai==2.30.0 after real SDK offline transport parity at Agent/Judge
interfaces. The lock adds openai and its distro 1.9.0, jiter 0.17.0, sniffio 1.3.1
and tqdm 4.70.1 dependencies; existing locked package versions remain unchanged.
httpx remains used by SDK tests and optional readiness probes; Jinja, jsonschema,
Pydantic and referencing retain their actual local validation/rendering roles.
SDK/HTTP/vLLM imports remain lazy: plain imports, CLI help/version/validation and
local schema construction acquire no live clients, files or server resources.

## Follow-up correctness review

The user's subsequent instruction to proceed triggered a focused review of the
implemented boundaries. [Ticket 06](issues/06-final-review-invariants.md#answer)
corrects two defects: Task construction now rejects nested NaN/infinities in
input/provenance, and callable Judges retain evidence from returned Judgment
values. Verdicts and weighted scores are still computed locally; supplied evidence
is frozen and recorded through Episode's normal sanitization. End-to-end tests
prove preservation in both per-message reviews and persisted final verification.
The follow-up adds eight regression cases and five source lines, no helper/class.
The current measurements and release results below include these corrections.

## Verification

All checks ran offline, with .venv/bin on PATH where subprocesses require the
installed command. The starting suite passed 355 tests. Retired wrapper/interface
tests were replaced with behavioral suites at the canonical owners; the new
suite passes 204 tests. Those counts do not establish equivalent coverage by
percentage; the following retained properties have explicit behavioral proofs.

| Behavior | Verification |
| --- | --- |
| Stable Task/Episode identity, roles, segments, structural Environments, concurrent Agent/Judge reuse | tests/test_generation.py |
| Per-message revisions, actionable private feedback, ordinary-text-only exhaustion, no rejected effects, Agent-local Tools | tests/test_generation.py |
| Real SDK parity on both APIs; no retry/state; malformed/refusal/incomplete classification; exact reasoning and ordered calls; nested typed schemas; redaction | tests/test_model_calls.py |
| Actual commit fsync failure before effects; open/seal/publication failures; immutable generation; append-only reverification; deadlines/cancellation/cleanup | tests/test_recording.py |
| Source formats/origins, source-versus-record failure, strict inert rendering, confinement, custom-reference isolation, one Episode across steps | tests/test_task_files.py |
| CLI workflow, historical views, selected verification export, read-only TUI navigation, output/index confinement | tests/test_cli_inspection.py |
| Inert import/help/version/validation and the recursive less-than-20-line contract | tests/test_import_safety.py |
| Existing launcher readiness, port/config errors, child ownership, signals, interruption and cleanup | tests/test_vllm_startup.py (23 tests) |

Final gates:

- PATH="$PWD/.venv/bin:$PATH" .venv/bin/pytest -q: **204 passed**.
- .venv/bin/ruff check . and .venv/bin/ruff format --check .: pass.
- PATH="$PWD/.venv/bin:$PATH" .venv/bin/mypy: strict types pass (27 files).
- UV_CACHE_DIR=/private/tmp/agentinstruct-uv-cache uv lock --check --offline: pass.
- uv sync --locked --offline: pass; no live inference.
- uv build --offline: wheel and source distribution build successfully.
- Built wheel contains exactly the current 17 .py files, byte-for-byte, plus
  py.typed and the SDK dependency metadata; sdist contains the same source set.
- Isolated -I/-B wheel import, without the checkout on the import path, leaves
  openai unloaded and executes an offline Task with unchanged Episode identity.
- Both historical JSON/JSONL fixture files match the captured starting bytes.

The direct-dialogue, function-tool, multi-tool, stepped-dialogue, seed-sources and
structured-quality entry points all ran successfully offline. They exercise
independent Tasks, ordered Tool results including safe errors, retained private
history across segments, Python preparation generators and a mocked real SDK
Judge. doubleword-medagent/review_smoke.py also runs offline successfully. Every
shipped task.toml package validates without inference.

The release workflow smoke uses explicit ordinary inputs yielding one accepted
and one deliberately failed Episode. CLI validate/run/inspect/export/reverify and
piped TUI navigation pass, failure evidence remains available, and reverification
leaves trace.json bytes unchanged. Wheel/sdist outputs and fresh smoke records are
under /private/tmp/agentinstruct-audit-dist and
/private/tmp/agentinstruct-final-release-audit-v3.

No live inference or paid domain run was performed. The migrated Doubleword entry
point retains explicit application client ownership, task selection and deadlines,
and accepted-only native/OpenAI/seed exports. Structural example predicates prove
message presence only; semantic correctness and generation outcome remain separate
application policies. generation_terminated now produces an explicit migration
error because Judge receives Messages rather than a Trace wrapper.

## Completed slices and records

1. [Task, Environment and Runner](issues/01-task-environment-runner.md#answer).
2. [Reusable Judge and callable Tool](issues/02-judge-and-tool.md#answer).
3. [Agent, SDK parity and Provider retirement](issues/03-agent-and-model-client.md#answer).
4. [Single Episode representation](issues/04-episode-recording.md#answer).
5. [Optional adapters, deletion and release gate](issues/05-optional-adapters-and-release.md#answer).

Follow-up: [06 — Strict JSON and callable judgment evidence](issues/06-final-review-invariants.md#answer).

Legacy lean-core tickets 08–10 were rebased to these interfaces and resolved;
their old deleted-module commands are no longer active instructions. README,
CONTEXT, migration notes and affected ADR implementation checkpoints describe the
implemented boundary. The user's earlier uncommitted changes were retained;
this work was not committed or published.
