# Inspection audit

Audited all 541 physical lines of `src/agentinstruct/inspection.py` on 2026-10-02. This is planning only; no inspection implementation changed.

The file reads saved Runs/Traces, exposes JSON projections, and formats operator output. It never generates data or invokes components. Run discovery also serves dataset export, so the whole file is not expendable UI code.

```text
saved manifest/index -> confined load_run -> RecordedRun/RecordedTrace
saved Trace/sidecars --------------------> Inspector
                                           -> summary/view -> CLI JSON
                                           -> render -> CLI text/TUI
load_run ---------------------------------> export Run discovery
```

## Complete inventory

KEEP means the responsibility earns a place in the current lean library. SIMPLIFY means the responsibility remains useful but its implementation or display scope can shrink. A caller establishes usage, not necessity; optional presentation cuts are evaluated separately below. No definition is demonstrably dead today.

| Definition; current line span | Assessment | Purpose and actual callers |
| --- | --- | --- |
| `RecordedTrace`; 22–25 | KEEP | Couples a saved path/snapshot with historical index status. Constructed by `load_run` and `Inspector`; export consumes `.path`, CLI/UI consume `.snapshot`. Exported publicly and used in README Run iteration. Avoid replacing it with parallel path/status arrays. |
| `RecordedRun`; 29–64 | KEEP | Ordered Run evidence and public discovery result; consumed by `Inspector`, export, README and release/hardening tests. |
| `RecordedRun.__post_init__`; 35–37 | KEEP | Freezes externally supplied manifest/traces. Public construction remains possible; read-only safety is not proved merely by current internal construction. |
| `RecordedRun.to_dict`; 39–64 | KEEP | JSON Run summary with current decisions and historical index counts kept separate. Called by `Inspector.summary`; asserted in moved-Run/reverification inspection tests. |
| `_IndexEntry`; 68–72 | KEEP | Four-field saved-index validation schema, instantiated by Pydantic inside `load_run`. This is data validation, not an execution component abstraction. |
| `load_run`; 75–113 | SIMPLIFY | Confined, ordered discovery with identity/duplicate checks. Called by `Inspector.__init__`, `export._export_paths`, public README usage, release/hardening/inspection tests. Reuse one `TypeAdapter` per load. |
| `_confined`; 116–120 | KEEP | Resolves and rejects escaped evidence paths; `load_run` calls it for manifest, index, Trace, snapshot, sidecar directory and sidecars. Calls whose return value is ignored still perform necessary validation. |
| `Inspector`; 123–366 | SIMPLIFY | One read-only snapshot facade for Run/Trace inputs. Used by CLI, canonical TUI, README, doubleword example and historical-fixture tests. Its projection/display scope, rather than the class shell, accounts for most code. |
| `Inspector.__init__`; 126–137 | KEEP | Selects Run discovery or standalone Trace loading and caches immutable evidence once. Later reverification requires a new Inspector, as documented. |
| `Inspector.summary`; 139–175 | SIMPLIFY | Current status, selected/latest Verification and aggregate metadata. CLI/UI/example call it. Reuse `_participants`; keep historical/current and selected/latest distinctions. |
| `Inspector.view`; 177–278 | SIMPLIFY | Operator JSON views and participant projection. CLI `--view` and UI commands expose every branch; README and tests use them. Merge participant filtering and role mapping into one pass. Optional themed views are feature costs, not dead branches. |
| `Inspector.render`; 280–366 | SIMPLIFY | Human-readable summaries, actor/turn/step labels, Tool details and review-exhaustion warnings. CLI default output, TUI and README call it. The largest optional formatting feature; see the concrete cut below. |
| `_verification_summary`; 383–392 | KEEP | Minimal JSON identity/status/score/error for selected and latest attempts; called by `Inspector.summary`. Valuable failure and append-only reverification evidence. |
| `_reasoning`; 395–465 | SIMPLIFY | Operator-only policies/call details across generation and Verification, including failed structured-output response evidence. Called by `view("reasoning")` and `_reasoning_summary`; six retention/outcome tests exercise both. This 71-line presentation feature can be retired only intentionally. |
| `_reasoning_summary`; 468–483 | SIMPLIFY | Counts returned/retained/suppressed calls without exposing text in summaries. Called by `summary`. Currently constructs the full detailed projection first; avoid promising large line savings from changing that scan. |
| `_participants`; 486–488 | KEEP | Shared participant identity extraction; called by `view` validation and `render`. It can also replace the inline duplicate in `summary`. |
| `_attempt_label`; 491–506 | SIMPLIFY | Selected/latest Verification text labels used by `render`. Repeats selection already performed by `summary`; consume its prepared attempt data instead. |
| `terminal_text`; 509–516 | KEEP | Escapes terminal controls from saved/external content. Called by `render`, CLI inspection failures and UI command errors. Keep even if bespoke display formatting is removed. |
| `_artifacts`; 519–541 | SIMPLIFY | Lists persisted regular artifact files/sizes without following symlinks or discovering unrelated standalone-file parents. Called by `view("artifacts")`; optional display capability with explicit retirement cost below. |
| `VIEWS`; 369–380 | KEEP | Existing view vocabulary used by `Inspector.view`, CLI argparse choices and UI command dispatch. Adjust only when a display feature is deliberately retired. |

## Concrete reductions

### Preserve all current features first

1. Reuse summary data in `render`: participant identities and selected/latest attempts are already available. Shorten `_attempt_label` rather than rescan the Trace. Estimated **8–12 deleted lines** including changed call sites; preserve exactly the current labels and `none` cases.
2. Combine participant filtering and role mapping into one tuple comprehension. Estimated **3–5 deleted lines** and one fewer intermediate collection. Keep `shared OR owned` visibility and role conversion exactly unchanged.
3. Create `TypeAdapter(_IndexEntry)` once before the index loop. This saves validator construction per Trace, **not meaningful source lines**. Removing the adapter/schema would sacrifice saved-data validation.
4. Remove per-directory `sorted(files)` in `_artifacts`: the complete result is already sorted afterward. This removes redundant work, **not a material physical-line reduction**; retain the final order and symlink checks.

Expect roughly **10–20 net lines** from straightforward duplication cleanup. There is no evidence for a large behavior-preserving deletion in this file. A new registry, generic dispatcher, record hierarchy or module split would not itself reduce this maintenance burden.

### Larger cuts require a display decision

These are optional presentation features, despite having callers. They are not proposed implementation work in Task 05.

| Optional decision | Estimated actual deletion in this file | Consequence |
| --- | --- | --- |
| Keep `render()` but replace bespoke text with escaped, indented JSON from the existing `summary()`/`view()` | **80–95 lines**: the current 87-line renderer becomes about 10 lines; the 16-line `_attempt_label` becomes unnecessary | JSON schemas and privacy projections can remain intact. CLI default/TUI output becomes more verbose JSON and loses concise human headings, step transitions and `REVIEW EXHAUSTED` emphasis; the underlying fields remain. Requires output/documentation/test changes. |
| Retire the dedicated reasoning view and summary counts | **90–95 lines**: `_reasoning` + `_reasoning_summary` total 87 lines, plus their small view/summary/vocabulary/display hooks | Model-call reasoning retention, privacy, failed-response evidence and Verification sidecars remain stored unchanged. Operators must inspect raw Trace/attempt events for policies, usage and retained reasoning; `inspect --view reasoning` and summary counters disappear. This is a feature retirement, not removal of reasoning support. |
| Retire artifact listing from inspection | **25–30 lines**: 23-line helper plus its view/vocabulary hooks | Persisted artifacts and Tool behavior remain intact, but the inspector stops listing paths/sizes. Users inspect the artifact directory directly. |

The three cuts together could remove roughly **190–210 lines**, with small overlap between renderer and reasoning hooks. They would leave this file around **330–350 lines**. These are estimates from current function spans, not claimed measured reductions. Prefer choosing the display capabilities actually needed over replacing them with new abstractions.

## Evidence and boundaries

- Production/public callers: `src/agentinstruct/export.py` (`_export_paths`), `cli.py` (`inspect`), `ui/terminal.py` (`InspectionSession`/`run_terminal`), `__init__.py` public exports; `examples/doubleword-medagent/run.py`; README's “Inspect persisted Runs and Traces” Python usage.
- `tests/test_inspection.py`: moved Runs/current versus recorded decisions; participant Tool ownership; operator views/artifact sizes; six generation/Verification reasoning retention/error cases; duplicated failed-response evidence; step/review-exhaustion labels; nine confined/identity/duplicate rejection cases; standalone/empty Runs; pagination/control escaping; custom streams/EOF/Ctrl-C without writes.
- `tests/test_refactor_compatibility.py`: historical snapshots remain inspectable without importing original task components. `tests/test_release_workflow.py` and `test_hardening.py`: export/reverification/discovery workflows use the reader.
- Actual Python source and task/example searches found no unused definition or task-selected inspection component. Private helpers are reached through the public reader, so absence of external private imports is irrelevant.
- Preserve ordered discovery, confinement/identity checks, immutable evidence, selected versus latest Verification, accepted-only participant projection, private reasoning boundaries and terminal sanitization through any later change. No new tests, feature retirements or production edits were made for this audit.

Self-review: inventoried all four defined classes, six explicit methods, nine module functions and the shared view constant against the full source; checked every entry against actual callers and existing tests. Estimates separate duplication savings from optional feature removal and do not double-count class spans as additional method code.
