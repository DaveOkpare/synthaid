# Seven-module implementation checkpoint

Date: 2026-10-03
Status: complete; all five authorized slices implemented

The user requested execution of the [library design specification](../.scratch/library-design-audit/spec.md).
The [final implementation report](../.scratch/library-design-audit/implementation.md)
and [migration guide](../docs/migration-seven-modules.md) record current APIs,
verification and exact source accounting. Earlier lean-core checkpoints remain
in their [work index](../.scratch/lean-core-refactor/map.md).

```text
application: prepare ordinary inputs and own endpoint clients for the batch
  -> Task(agents, input, segments, verifier): create Episode and UUID immediately
  -> Runner(tasks, output_dir, client): open each existing Episode; construct Environment
     -> Environment(task, client).run(): prepare owned resources; activate segments
        -> Agent.generate -> own Judge/revise -> durable acceptance -> own Tools
     -> bounded cleanup -> seal generation once -> optional final Judge
  -> collect Task.episode; inspect/export or append independent verification
```

Task, Agent and Judge construction validates locally and acquires no resources.
The application initializes and closes SDK clients; execution borrows them without
premature closure. Agent/Task inputs are stable. Episode and invocation locals
isolate accepted history, private Tool exchanges, drafts and revision counters.
Each new sample constructs a fresh Task while reusing configured Agents/Judges.

[ADR-0025](../docs/adr/0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
implements the constructor/run boundary, one-Task-per-execution policy and pinned
SDK after parity. This replaces earlier public setup/context ownership and
Provider/Run-store APIs. There are seven primary root imports and no obsolete
Python aliases. Task requires assistant and optionally user; Tools/reviewers are
Agent-local, and the final verifier is Task-local.

## Completed work

1. Task, Environment and Runner: stable construction-to-output identity, structural
   custom Environments, ordered segments, private history and explicit client/resource ownership.
2. Judge and Tool: reusable callable/model evaluation, exact weighted verdicts,
   per-Agent assignments and strict input/result/error contracts.
3. Agent and SDK: private actionable revision feedback, independent message budgets,
   concurrent reuse, both HTTP APIs, stateless requests and strict local wire/schema checks.
4. Episode: one representation, durable intent/results, output confinement,
   immutable generation, append-only verification and historical records.
5. Optional interfaces: inert source compilation, one Task across phases, CLI/TUI/
   inspection/vLLM migration, deletion, documentation and the offline release gate.

The [slice tickets](../.scratch/library-design-audit/map.md) and rebased lean-core
08–10 are resolved. Historical instructions naming deleted modules are superseded.

The subsequent [correctness review](../.scratch/library-design-audit/issues/06-final-review-invariants.md#answer)
rejects nonfinite JSON at Task construction and preserves custom Judgment evidence
through review/final recording. It adds eight regression cases and no owners/helpers.

## Final verification

204 deterministic tests pass with live network blocked. Ruff lint/format and
strict mypy pass. Locked offline sync/check and wheel/sdist builds pass. The wheel
contains the current source bytes, imports without eagerly loading the SDK and
executes an offline Task independently of the checkout. Historical fixture bytes
are unchanged. Direct examples, the mixed accepted/failed CLI release workflow,
accepted-only exports, immutable reverification and read-only TUI navigation pass.
The existing 23 vLLM startup tests retain process/readiness/signal behavior.
No live inference or paid domain run was required.

Every shipped function/method is fewer than 20 inclusive physical lines, including
signatures and blanks, excluding decorators. Final source is 4,293 lines across
17 files, 26 classes and seven root exports. Core: eight files / 2,367 lines;
optional: nine files / 1,926 lines. Net deletion from the captured working-tree
baseline is 3,108 lines (42.0%). Function definitions rose from 287 to 295 and
private non-dunder definitions from 109 to 214; the report makes that extraction
cost and external SDK dependency explicit. No commit or publication was requested.
