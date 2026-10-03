# 05c: Delete Plans and use a lean task loop

Type: implementation
Status: resolved
Blocked by: 05
Date: 2026-10-02

## User direction

Delete plans.py and agent_tool.py completely. Remove ToolPlan, ToolContext,
StepProgress and CONTROL_TOOLS. Runner takes an actual Environment and ordinary
task records. Keep task files as an optional adapter. Agents own their Review;
final Verification is independent. No replacement Plan hierarchy or aliases.

## Authorized dependent slices

1. Agent/Provider/schema: direct dependencies, actual request declarations;
   remove ModelAgent and all provider/profile/Plan catalogs.
2. Episode/Tools: durable recording, one-argument Tools, remove AgentTool and
   step-state owners. Ordinary closures capture task data.
3. Adapter/data/quality: delete plans.py and task_config.py; retain only JSON
   utilities and input records, parse task files into frozen mappings, construct
   actual dependencies outside Runner. Migrate quality calls and historical readers.
4. Runner: loop records, lifecycle/cleanup/seal/final Verification/publication;
   no factories or per-message Review loop. Close partial preparation resources.
5. Migrate actual callers/tests/docs and prove both provider APIs, invalid input,
   private effects, cleanup, immutable/append-only evidence and saved Trace reads.

This replaces unfinished 05b and directly covers the requested Runner work in
06. It does not authorize unrelated future optimization tickets. Stop at the
code review checkpoint after this implementation.

## Test migration

The former 599-test checkpoint exercised APIs now explicitly removed. It is not
an acceptance count for the new architecture. Keep CLI/path/import/startup and
historical-artifact protections; migrate schema, seed, inspection and final
Verification suites. Direct execution/provider/Runner suites cover actual owners.
Tests dedicated to retired factory/Plan/AgentTool/step-control/profile APIs are
removed from active tests; their original source remains in Git history. Do not
keep compatibility code solely to satisfy these old contracts.

Replacement coverage: test_episode, test_lean_execution, test_lean_agents,
test_lean_providers, test_lean_runner, test_structured_output, test_seed_sources,
test_verification, test_inspection, test_task_adapter, test_tool_effects,
test_cli, test_package_safety, test_import_safety, test_refactor_compatibility,
and test_vllm_startup. Current results and size accounting follow in Answer.

Retired active modules: test_collections, test_components, test_dialogue,
test_hardening, test_model_quality, test_providers, test_release_workflow,
test_responses, test_review, test_runner, test_steps, test_tools, test_vllm and
component_fixtures. They require removed Plan/factory/AgentTool/profile/step
contracts and are preserved in Git history, rather than copied into another
active directory. Meaningful runtime protections move to the direct suites;
verification, schemas, seeds, inspection, CLI and path/import suites retain
their behavior assertions with explicit caller migration. No old 599-test pass
claim is made.

## Answer

Completed the user-authorized replacement and stopped at the code review checkpoint.

Deleted plans.py, agent_tool.py, model_agent.py, steps.py and task_config.py.
No Plan/config hierarchy or forwarding aliases were moved elsewhere. data.py
contains 76 existing JSON utility lines; Seed/SeedOrigin are actual input records.
Provider connections, Agent attributes, Tools and quality owners are actual
objects. Raw authoring and historical evidence use frozen ordinary JSON mappings.

Runner takes Environment plus records. Task-file dependency binding lives in
TaskPackage.prepare_tasks, outside the core loop. Application/file phases are
independent records; step_id is archival attribution only. Each Agent owns its
Reviewer/revisions, and final Verification observes sealed evidence independently.

Partial binding/startup cleanup is protected. Invalid seeds retain identity,
origin/raw/digest. Schema definitions use captured source bytes and an offline
registry. Strict policy values reject textual Boolean fallback before runtime
construction. CSV reverification retains flat-column origin semantics, including
historical saved metadata. Reverification appends decisions without modifying
sealed generation. Examples and active callers migrate explicitly.

Verification: 332 current deterministic tests pass; full Ruff lint/format and
strict mypy (47 source/test files) pass. Locked offline dependency check and
sdist/wheel build pass. Built-wheel proof covers retired modules absent, actual
retail generation, adapter validation/run, static inspection/export and immutable
reverification, with no vLLM SDK/TUI import. All 15 example packages validate;
eight offline CLI examples and five Python scripts run. Live/GPU inference was
not used and no live endpoint capability claim is made. The former 599-test suite
is explicitly superseded, not falsely reported as passing unchanged.

Recursive physical source accounting (including blank/doc lines):

| Measure | Last completed 05 | Current 05c | Change |
| --- | ---: | ---: | ---: |
| All Python lines | 8,862 | 7,397 | -1,465 |
| Core lines | 8,573 | 7,108 | -1,465 |
| Integration lines | 165 | 165 | 0 |
| Terminal UI lines | 124 | 124 | 0 |
| Python files | 32 | 28 | -4 |
| Classes | 154 | 95 | -59 |
| Public exports | 76 | 49 | -27 |

There are no compatibility forwarding files. These are actual net deletions,
not relocation. Total source is 2,043 lines below the original 9,440-line baseline;
this checkpoint does not claim the later planned 6,500-core-line target is met.
Existing local schema, durability, privacy and failure checks remain code rather
than being removed for counting. No unrelated later ticket is started.
