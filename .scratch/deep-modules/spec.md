# Simplify the generation library through deep modules

Type: specification
Status: resolved
Date: 2026-10-03
Baseline: verified checkpoint 6de2613 (4,293 source lines; 204 tests)

The user requested review/fixes, a checkpoint commit, then further simplification
using clean Python and domain-independent protocols. Environment was specifically
identified as containing unnecessary machinery. This instruction refines the
previous seven-module implementation; preserving speculative resource/configuration
features is no longer a goal.

## Direction

Keep Task/Episode as concrete data owners. Use small structural protocols where
behavior actually varies: generation, evaluation and Task execution. Keep the
built-in Agent/Judge/UserSimEnv usable while allowing plain domain adapters.
Preserve proposal review, durable intent before Tools, strict local JSON/schema,
private history, immutable recording, historical reads and borrowed client ownership.
Retain the fewer-than-20-line function contract without compressed code.

## Slices

1. Delete Environment-owned generic resource management and verifier assembly.
   Applications own external resources. Task receives a ready evaluator. Remove
   duplicate model dependency checks; Agent validates when invoked. Narrow Runner's
   Environment dependency through a structural execution protocol.
2. Introduce structural generation/evaluation seams with actual domain examples.
   Framework approval and recording continue to wrap custom generation. Avoid
   obliging custom evaluators to carry SDK configuration or inherit Judge.
3. Simplify remaining repeated conversion/validation paths by owner, without
   recreating Provider/store/config layers or loosening required checks.
4. Update affected tests/docs/ADRs, measure deleted concepts and helpers, run the
   offline release gate, and commit verified increments.

## Answer

All four slices are implemented and verified after the requested checkpoint commit. See the [implementation report](implementation.md), [metrics](metrics.json) and [resolved work map](map.md).

## Runner scope correction

The user rejected Runner-owned lifecycle after commit 5367d23. Restore the original library specification: Runner only opens, invokes Environment and collects Episodes; Environment owns execution/finalization. Keep the structural protocols and application-owned resources. Track this correction in [ticket 05](issues/05-restore-runner-loop.md).

The Runner correction is implemented and verified. [runner-correction.md](runner-correction.md) and ADR-0027 describe current ownership; prior report measurements remain historical.
