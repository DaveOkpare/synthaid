# Domain protocols and simpler execution

Type: implementation report
Status: resolved
Date: 2026-10-03
Baseline: verified commit `6de2613`

The review/fixes and seven-module implementation were committed first as
`6de2613` on `codex/deep-module-refactor`. This subsequent pass removes speculative
Environment machinery and adds structural seams exercised by real domain adapters.
[ADR-0026](../../docs/adr/0026-use-domain-protocols-and-runner-owned-task-lifecycle.md)
and the [migration guide](../../docs/migration-seven-modules.md) define the changed API.

## Design

- Environment is a one-method protocol: `async run(task, *, client=None)`.
  Runner accepts an implementation instance. The default stateless UserSimEnv only
  activates segments and schedules the existing assistant/user Agents.
- Runner owns recording, the Task deadline, failure/cancellation outcomes, generation
  sealing and optional final verification. Custom Environments receive the same
  lifecycle without reproducing it. Task supplies its declaration and participant order.
- Applications own clients and external async contexts. Environment no longer carries
  resources, context stacks, shielded cleanup, verifier factories or duplicate model
  preflight. No alternate runtime owner, registry or service container replaces them.
- Agent accepts a plain Generator; reviewers and Task verifiers accept plain Evaluators.
  These protocols each have one operation. Task/Episode stay concrete data owners;
  Agent retains proposal validation, revision, durable acceptance and approved effects.
- Custom evaluators must return a validated Judgment. A truthy object cannot authorize
  effects or final acceptance; scores reject Booleans, nonfinite numbers and values
  outside zero to one. Custom evaluators need no SDK configuration attributes.
- Evaluation failures that were durably recorded leave verification unverified and
  allow the batch to continue, including a plain evaluator's OSError. Verification
  publication failures propagate; they cannot silently disappear.
- Generation accepts immutable sequences as well as single Messages. The retail
  example and task-file scripted implementation use plain generators. Arithmetic
  generation/evaluation and custom execution demonstrate independent domain reuse.
- JSON freezing validates/projects each tree once, then freezes the validated tree.
  A cached validator replaces repeated construction. JSON parsing retains duplicate-key
  and nonfinite-number rejection without re-encoding the entire result. Tools use
  that validated JSON projection without redundant serialization passes.

Agent.generate overrides remain supported. Direct Python callers replace
`Environment(task).run()` with Runner execution and supply ready Task evaluators.
The removed resources/verifier-dictionary API is deliberate. Optional task-file
custom references retain their documented authoring contract; the loader prepares
these same objects before execution. Root imports remain the same seven names.

## Measurements

[metrics.json](metrics.json) records every shipped Python file and qualified helper
identity. Physical lines include blanks; AST counts include nested functions. Function
length includes signature/body and excludes decorators.

| Measurement | Checkpoint 6de2613 | This pass |
| --- | ---: | ---: |
| environment.py lines | 196 | 45 |
| Environment + Runner + Task lines | 334 | 257 |
| Core source lines (8 files) | 2,367 | 2,345 |
| Optional source lines (9 files) | 1,926 | 1,926 |
| Total source lines (17 files) | 4,293 | 4,271 |
| Classes | 26 | 29 |
| Function definitions | 295 | 292 |
| Private non-dunder definitions | 214 | 205 |
| Root exports | 7 | 7 |
| Functions with at least 20 physical lines | 0 | 0 |

Environment is 77.0% smaller, and the combined execution/data modules lose 77 lines.
Moving lifecycle into Runner accounts for some of that change. New protocols and
boundary validation offset most line deletion elsewhere: this pass removes only
22 total source lines and nine private definitions. The three additional classes
are the three structural protocols, not additional execution owners.

Against the original captured working tree, source is 7,401 to 4,271 lines (42.3%
net deletion), 28 to 17 files and 94 to 29 classes. That is the cumulative refactor,
not the incremental result of this pass. Agent (983 lines) and the optional loader
(929) remain largest; pinned SDK parity, strict schemas and supported authoring/source
formats still account for substantial code. This does not claim every file is minimal.

An isolated comparison of the exact checkpoint/current freeze functions used a
20-row nested JSON payload and three samples per version. Canonical JSON was
identical; median time was 80.628 ms before and 0.081 ms after on this host. This
bounded operation benchmark does not establish whole-application throughput.

## Verification

- 222 deterministic tests pass with live network isolated, including new protocol
  adapters, malformed evaluation, normalized scores, domain failure/deadline recording,
  cancellation, verification publication failures, non-JSON Tool input rejection,
  durable Tool approval, immutable/private history and both SDK APIs.
- Ruff lint/format, strict mypy (28 source files), recursive function-size checks and
  locked offline dependency checks pass. The existing 23 vLLM startup tests pass.
- Offline wheel/sdist build succeeds; the wheel matches all 17 source files byte for
  byte, includes py.typed, imports without eagerly loading the SDK, and executes an
  offline Task independently of the checkout. Historical fixtures remain unchanged.
- All 15 shipped task packages compile offline (21 valid records). Seven direct
  examples pass. CLI validate/run/inspect, accepted-only native/OpenAI
  exports, reverification without generation mutation and TUI navigation pass on a
  mixed accepted/failed batch. Failed input remains visible rather than disappearing.

No live inference or paid run was needed. Packaging, optional workflows and the core
all exercise the same execution/proposal/evaluation owners.
