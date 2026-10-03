# Restore the specification's Runner scope

Type: implementation report
Status: resolved
Date: 2026-10-03
Baseline: 5367d23

The user rejected moving lifecycle work into Runner and pointed back to the
[original specification](../library-design-audit/spec.md). Its responsibility
split is restored in [ADR-0027](../../docs/adr/0027-restore-runner-to-the-task-loop.md).
The earlier protocol report and measurements describe historical commit 5367d23.

Runner now has only initialization and the Task loop. For each prepared Task it
opens the existing Episode at output_dir / episode.id, awaits the supplied
Environment.run(task, client=...), and collects the Episode. It has no private
helpers or execution/error/deadline/judgment/resource policy.

UserSimEnv.run owns the required execution safeguards: register client secrets
before recording declarations, begin execution, apply the Task deadline, execute
segments, record outcomes, seal generation and invoke final verification. The
Episode still owns durable recording and verification invariants. Required
behavior is consolidated with its specified owner. Generic resources, shielded
cleanup, verifier factories and duplicate dependency preflight stay deleted.
There is no added lifecycle wrapper, module, owner class or runtime registry.

Custom Environments own their run semantics. Runner propagates their errors
unchanged and does not apply limits or finalize on their behalf. The one-method
protocol instance interface remains. Domain generators/evaluators can keep the
default Environment's safeguards, and standalone UserSimEnv runs after the caller
opens task.episode. Agent/Evaluator/Tool behavior remains intact.

## Measurements

[runner-metrics.json](runner-metrics.json) compares shipped Python source with
commit 5367d23 using the same physical-line/AST method as the prior reports.

| Measurement | Before | After |
| --- | ---: | ---: |
| runner.py lines | 104 | 31 |
| Runner functions | 7 | 2 |
| Runner private helpers | 5 | 0 |
| environment.py lines | 45 | 116 |
| Runner + Environment lines | 149 | 147 |
| Core source lines | 2,345 | 2,343 |
| Total source lines | 4,271 | 4,269 |
| Classes / functions / private definitions | 29 / 292 / 205 | 29 / 292 / 205 |

This corrects responsibility placement; total source drops by two lines. The
Environment includes necessary behavior formerly placed in Runner, so the prior
45-line Environment measurement is historical. It remains below the 196-line
checkpoint before protocol simplification. All shipped functions remain below
20 inclusive physical lines; the longest is 19. Root exports remain seven.

## Verification

225 offline tests pass, including explicit ordered Runner invocation, stable
Episode identity/client forwarding, no Runner deadline/finalization policy,
unchanged custom error/cancellation propagation, and standalone Environment
success/failure/deadline execution. Four previous custom-Environment cases now
assert the corrected ownership contract. Existing SDK parity, Tool durability,
privacy, failure/cancellation and immutable reverification checks pass.

Ruff lint/format and strict mypy pass. Offline wheel/sdist build, byte-for-byte
source packaging and isolated wheel execution pass. Direct examples and the
mixed accepted/failed CLI/export/reverification/TUI workflow pass. No live
inference was needed.
