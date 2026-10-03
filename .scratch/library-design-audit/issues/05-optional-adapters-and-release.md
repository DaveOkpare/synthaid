# 05: Optional adapters, deletion and release gate

Type: implementation
Status: resolved
Date: 2026-10-03

## Description

Replace TaskPackage/Seed/registry machinery with one inert adapter; retain CLI/Inspector/TUI/vLLM against canonical core imports, migrate examples and document deletion and API changes.

## Answer

Implemented under the user's authorization to execute [the specification](../spec.md).
All source functions are fewer than 20 inclusive lines. Full 204-test suite, strict types, Ruff, lock, wheel/sdist byte parity, isolated built-wheel execution, offline examples, CLI release smoke and historical fixtures pass. Exact source/helper accounting is in the final report.

See [the implementation report](../implementation.md) for source accounting,
release evidence, migrations and limits. Later corrections from final review are
included in this completed slice; no live inference was required.
