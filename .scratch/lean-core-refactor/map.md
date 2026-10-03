# Lean core refactor work index

Status: resolved
Type: effort

Current implementation: all tickets are resolved, including rebased 08–10 under
[the completed seven-module plan](../library-design-audit/spec.md). The
[final implementation report](../library-design-audit/implementation.md) records
204 passing tests and source reduced from 7,401 to 4,293 lines. The following
checkpoints preserve earlier user review history and their superseded interfaces.

Preserve active generation behavior and task files; unused compatibility aliases are retired under ADR-0009. Keep Responses/Chat Completions in the core; use their shared transport for vLLM endpoints and isolate the TUI. The user's Task 02 review rejects the packaged conformance framework; its completed retirement is recorded in Task 03. Each Agent owns message Review; ADR-0012 assigns final Verification to Environment, implemented in 06b.

- [Specification](spec.md)
- [Implementation plan](../../tasks/plan.md)
- [Interface/seam sketch and domain example](interfaces.md): consult before changing Agent ownership or Runner assembly in tickets 05–06.

| Ticket | Status | Blocked by |
| --- | --- | --- |
| [01 — Compatibility baseline](issues/01-record-compatibility-baseline.md) | resolved | — |
| [02 — Isolate vLLM execution](issues/02-isolate-vllm-execution.md) | resolved | 01 |
| [02a — Explicit vLLM startup](issues/02a-vllm-startup.md) | resolved | 02 |
| [03 — Share transport and cut vLLM certification](issues/03-isolate-vllm-models.md) | resolved | 02 |
| [03a — Shared transport](issues/03a-shared-transport.md) | resolved | 02 |
| [03b — Packaged startup](issues/03b-packaged-startup.md) | resolved | 02a |
| [03c — Retire conformance](issues/03c-retire-conformance.md) | resolved | 02 |
| [04 — Isolate terminal UI](issues/04-isolate-terminal-ui.md) | resolved | 01 |
| [04a — Remove unused compatibility](issues/04a-remove-unused-compatibility.md) | resolved | 03, 04 |
| [05 — Agent-owned Review](issues/05-agent-owned-review.md) | resolved | 01 |
| [05b — Concrete Agent/Environment/Episode](issues/05b-concrete-agent-environment-episode.md) | resolved (superseded) | 05 |
| [05c — Delete Plans and lean task loop](issues/05c-remove-plans-and-lean-task-loop.md) | resolved | 05 |
| [06 — Simplify Runner assembly](issues/06-simplify-runner-assembly.md) | resolved (covered by 05c) | 03, 05 |
| [06a — Short Runner lifecycle](issues/06a-short-runner-lifecycle.md) | resolved | 05c |
| [06b — Minimal Runner and Environment Episodes](issues/06b-minimal-runner-and-environment-episodes.md) | resolved | 06a |
| [07 — Consolidate authoring invariants](issues/07-consolidate-authoring-invariants.md) | resolved | 03 |
| [08 — Share model-call evidence](issues/08-share-model-call-evidence.md) | resolved | 05, 06 |
| [09 — Simplify seed preparation](issues/09-simplify-seed-preparation.md) | resolved | 07 |
| [10 — Verify and document](issues/10-verify-and-document.md) | resolved | 04, 06, 08, 09 |

Tasks 01 and 02 are complete; see the [compatibility inventory](baseline.md) and [Task 02 answer](issues/02-isolate-vllm-execution.md#answer) for code, verification, and size accounting. Task 03 was revised following user review to reuse the existing compatible transport and remove the certification framework. The user authorized Task 03 on 2026-10-01; its three bounded slices are complete. The [Task 03 answer](issues/03-isolate-vllm-models.md#answer) records the 586-test suite, packaged short command, and actual net source reduction. Task 04 is complete; its [answer](issues/04-isolate-terminal-ui.md#answer) records UI isolation, compatibility, 597 passing tests, package checks, and honest relocation accounting. Tasks 06–10 remain unclaimed for later review checkpoints. Resolve dependencies before claiming a ticket. Checkpoints and required verification are in the implementation plan.

The user separately authorized Task 02a; its [answer](issues/02a-vllm-startup.md#answer) records the completed program-boot launcher, 21 new tests, final 578-test suite, and separate size accounting. It does not start Task 03 or change provider ownership.

The user subsequently retired unused compatibility paths in [04a](issues/04a-remove-unused-compatibility.md#answer): vllm.py and inspection/facade aliases are deleted, 76 exports remain, and the 596-test suite passes. Shipped source is 8,879 lines (92 deleted in this slice); no compatibility-only tests keep production wrappers alive.

Task 05 is complete; its [answer](issues/05-agent-owned-review.md#answer) records the single Interaction owner, 17 deleted source lines, 599 passing tests and package proof. Review [file-audit.md](file-audit.md) and [inspection-audit.md](inspection-audit.md) for per-definition decisions and concrete future cuts. Task 06 remains unclaimed at the user review checkpoint.

The user subsequently replaced the Task 05 interface with concrete Agent ownership and direct Environment scheduling. [05b](issues/05b-concrete-agent-environment-episode.md) implements that replacement under ADR-0010; the previous 05 answer remains historical. Task 06 is not claimed.

Historical authorization: [05c](issues/05c-remove-plans-and-lean-task-loop.md) supersedes 05b and covers the directly requested Runner change in 06. ADR-0011 retires all Plan/factory/context/control APIs; task files stay an adapter and historical JSON stays readable. Later unrelated tickets await review. Earlier counts remain historical checkpoints.

[05c answer](issues/05c-remove-plans-and-lean-task-loop.md#answer): deleted Plan/config/context/factory/control ownership, direct task loop and optional file adapter;332 current tests and offline quality/package gates pass. Source7,397 lines/28files/95classes/49exports;1,465 actual net lines removed from05. Paused at user code review, later07–10 unstarted.

Historical checkpoint: [06a answer](issues/06a-short-runner-lifecycle.md#answer).
The user prioritized shortening `_run_tasks` and limiting functions to 20 lines.
Every Runner function now meets the inclusive limit; `_run_tasks` is 19 lines.
334 tests and all offline quality/package gates pass. Runner source is 454 lines
versus 455 before; shipped Python source is 7,396 lines. This slice improves
readability, with 32 private/public definitions versus 9 before; no new classes,
dependencies or public exports. Stopped for code review; later 07–10 unstarted.

Historical accepted direction: [ADR-0012](../../docs/adr/0012-keep-runner-as-an-environment-task-loop.md).
Runner only iterates prepared tasks/segments and calls its Environment. Lifecycle,
recording and optional final Verification belong outside Runner. Environment
invokes the Verifier after a whole Episode's conversation ends, including multiple
user/assistant rounds. This supersedes the lifecycle ownership retained at the
06a checkpoint and is implemented in 06b.

Historical checkpoint: [06b answer](issues/06b-minimal-runner-and-environment-episodes.md#answer).
Runner is 23 lines/two methods; Environment owns complete Episodes and final
Verification; the optional adapter/store retain task preparation and Run outputs.
354 tests and all offline gates pass; changed/new functions meet the inclusive
20-line limit. Shipped source is 7,413 lines (+17), 28 files, 94 classes and 49
exports. This fixes ownership; total source remains roughly unchanged. Stopped
for user code review; later unrelated tickets 07–10 remain unstarted.

Historical checkpoint: [07 answer](issues/07-consolidate-authoring-invariants.md#answer).
The former Plan duplication was covered by 05c; the follow-up deletes unused
directory options and repeated diagnostics. TaskPackage loses 12 actual lines;
source is 7,401 lines, 28 files, 94 classes and 49 exports. 355 tests and all
offline gates pass, with exact baseline records/errors preserved. Environment
cuts remain deferred; later 08–10 are unstarted. Stopped for user code review.
