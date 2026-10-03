# 05: Put Review inside the Agent runtime

Type: implementation
Status: resolved
Blocked by: 01

## Description

Unify the current AgentHandle/Interaction state into one internal per-Agent runtime owning observation projection, proposal generation, Review/revision, private Tools, and accepted replies. Keep user Agent.generate implementations and Environment interaction hooks compatible.

## Acceptance criteria

- [x] The per-Agent runtime holds its Reviewer, active rubric, revision budget, and Tool-turn processing; Environments only schedule turns and the Runner has no message-review loop.
- [x] Existing `Agent.generate`, `Agents`, `interaction(task)`, incoming reply validation, list actions, and control messages work through this one state owner.
- [x] Rejected Tool proposals produce zero effects; accepted intent/results remain durable; private Tools, step history, revision exhaustion, and failed partial Traces retain behavior.

## Verification

Run `uv run --locked pytest tests/test_review.py tests/test_tools.py tests/test_steps.py tests/test_dialogue.py tests/test_release_workflow.py tests/test_components.py` and strict typing. Inspect review events and accepted messages from the offline release example.

## Likely files and scope

Small: `execution.py`, `runner.py`, up to two behavior-test files, and the README's ownership description. Keep one runtime rather than introducing another public Agent class. Split unrelated model-call recording into ticket 08.

## Implementation decision — 2026-10-02

The user authorized Task 05 and requested file/class/function usage audits. `Interaction` already implements the entire acceptance loop; `AgentHandle` only constructs it and yields it. Delete that wrapper and put `interaction(task)` on the existing `Interaction`, yielding itself. `Agents` and Runner reference this one object directly. Retain the canonical `Interaction` name because it describes the active extension hook and is used by the sealed-generation behavior test; no renamed class, forwarding alias, or additional module is needed.

The Reviewer, active rubric, revision budget and Tool processing remain owned by this same object. Runner's existing dependency construction/preflight is assembly, not a second message-review loop; simplify that separately in Task 06. Audit `inspection.py` read-only alongside this slice and record concrete candidates before changing its behavior.


## Answer

Completed under the user's 2026-10-02 authorization. Removed `AgentHandle`; `Interaction.interaction(task)` yields itself, `Agents` maps IDs directly to Interactions, and Runner constructs this one owner. The existing acceptance loop already held the Reviewer, active rubric/revision policy and private Tool processing; all 13 prior Interaction methods are AST-identical. No new runtime class, alias or module was added. Runner still performs dependency assembly/preflight and lifecycle/final Verification; its construction duplication belongs to Task 06.

Three new behavioral cases cover both orderings of distinct per-Agent feedback/rubrics/revision budgets and a custom Environment reopening an interaction while retaining Agent counters, accepted history and Reviewer state. Existing zero-effects, Tool privacy, steps, list actions, cancellation, sealed generation and partial-failure tests remain.

Validation: **599 tests passed in 60.82s**, including the offline release workflow and all five statuses; focused ownership/safety suite **191 passed**. Global Ruff check, format (176 files), strict mypy (57 files), locked offline dependency check and whitespace check pass. Wheel/sdist build successfully under `/private/tmp/agentinstruct-task05-dist`; every shipped Python byte matches source. The built wheel independently generates two accepted release Traces, loads/inspects their Run and exports two dataset records. No Provider/GPU inference was run.

Implementing agents each completed self-review; independent review found no actionable issues and confirmed preserved runtime methods and constructor inputs.

Measured source: execution **731 -> 714 lines**, Runner **669 -> 669**. **17 lines and one class deleted, none relocated.** Total shipped Python **8,879 -> 8,862 lines**, 32 files, 154 classes, 76 top-level exports. Core 8,573; integration 165; UI 124; compatibility-only source 0. This is 578 source lines below the original 9,440-line baseline. Further cuts remain separate tasks; line-count targets are not yet achieved.

Usage decisions are in [file-audit.md](../file-audit.md). The separate [inspection inventory](../inspection-audit.md) reviews every class/function, identifies roughly 10–20 lines of behavior-preserving duplication cleanup, and estimates larger optional display retirements with explicit consequences. Inspection production code was not changed in this slice.

Task 06 remains unclaimed pending the user's code review; no later implementation began.
