# 04: Isolate the terminal UI

Type: implementation
Status: resolved
Blocked by: 01

## Description

Separate terminal navigation/input handling from persisted Trace reading and static inspection. Preserve `InspectionSession`, `run_terminal`, current views, and `inspect --tui`.

## Acceptance criteria

- [x] Terminal implementation lives in `ui/terminal.py`; old names forward to it with no second navigation implementation.
- [x] Static/JSON inspection and ordinary library startup remain independent of terminal UI import; explicit TUI use loads it lazily.
- [x] Existing navigation, rendering safety, views, stdin/EOF behavior, and CLI exit codes remain unchanged.

## Verification

Run `uv run --locked pytest tests/test_inspection.py tests/test_cli.py tests/test_import_safety.py` and focused lint/type checks. Check static and terminal inspection on the existing offline release output.

## Likely files and scope

Five logical units: relocation/old-path compatibility (`inspection.py`, `ui/terminal.py`, namespace initializer); lazy CLI selection (`cli.py`); lazy public facade (`__init__.py`); behavioral compatibility (`tests/test_inspection.py`); import isolation (`tests/test_import_safety.py`). Associated documentation/tracker updates record the result. The default wheel continues to ship the TUI. Keep `terminal_text` in static inspection because static terminal rendering also requires control-character escaping; only navigation and interactive input move.

## Comments

2026-10-02: The user authorized the next task after reviewing Task 03. Existing delegation and each agent's own review remain in effect. Preserve the cumulative worktree for user review; no commits. No launcher logging or deployment-manager changes are included in this terminal-isolation slice.

## Answer

Resolved 2026-10-02. Moved the 116 unchanged lines implementing `InspectionSession` and `run_terminal` into `src/agentinstruct/ui/terminal.py`. The canonical UI owns navigation, pagination, and interactive stream handling. Static reading/rendering and `terminal_text` escaping remain in `inspection.py`; static/JSON inspection and ordinary startup/generation never import the UI namespace.

Legacy `inspection.InspectionSession`, `inspection.run_terminal`, and the top-level class resolve lazily to the canonical objects. Signatures, views, privacy, read-only behavior, EOF/Ctrl-C/custom streams, CLI flags, and exit codes remain intact. Independent review found a fresh wildcard-import omission; the fix preserves all 25 original public exports, including TextIO, and is tested before any lazy attribute cache is populated. All 78 top-level exports remain.

The implementation and testing agents each reviewed their changes. Independent read-only review confirmed the wildcard fix and found no remaining actionable issues. Both moved definitions and retained static definitions have unchanged AST bodies. No navigation implementation is duplicated.

### Verification

- **597 tests passed in 57.74s**, including historical saved-artifact and offline release coverage. Added 11 meaningful cases for optional-module isolation, static success/failure paths, compatibility, and custom-stream shutdown.
- Whole-repository Ruff check and format (174 files), strict mypy (58 files), locked offline dependency check, and whitespace checks pass.
- Wheel/sdist builds and archive checks pass. Every Python file in the wheel matches source; UI is packaged, py.typed retained, retired vLLM modules remain absent, and no engine dependency was introduced.
- Built-wheel fresh imports/dir/static JSON inspection leave UI unloaded; explicit legacy wildcard imports and terminal navigation work without SDK/client imports.
- Ran the existing offline release example into `/private/tmp/agentinstruct-task04-release/26de716488ed466ebf1193e8630a5bfe`; both Seeds were accepted. Real installed CLI static/JSON inspection and terminal commands for trace/conversation/tools/next/quit succeeded on that saved Run.

### Source accounting

Counted all shipped Python recursively, including blank/docstring lines. This checkpoint relocates behavior, rather than deleting it.

| Category | Task 03 | Task 04 |
| --- | ---: | ---: |
| Core (includes mixed-module compatibility code) | 8,728 | 8,641 |
| vLLM integration | 165 | 165 |
| Terminal UI | 0 | 124 |
| Standalone legacy vLLM compatibility | 41 | 41 |
| Total shipped | 8,934 | 8,971 |

116 behavior lines moved; none deleted. The UI module/imports/namespace and lazy/public-export compatibility add 37 net lines. Source now comprises 33 Python files and remains 469 lines below the original 9,440-line baseline. Do not count the 87-line core reduction as deletion. No dependencies changed, no commits were made, and no launcher/deployment-manager behavior was changed in this task.

Task 05 (Agent-owned Review) and later stages remain unstarted for user review checkpoints.
