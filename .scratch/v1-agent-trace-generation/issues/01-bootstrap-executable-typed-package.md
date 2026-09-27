# 01: Bootstrap an executable typed package

**What to build:** Establish an installable, typed Python 3.13 library and thin command-line application that contributors can set up, test, lint, format, and build entirely through uv.

**Blocked by:** None (can start immediately)

**Status:** resolved

**Type:** implementation

- [x] A fresh checkout can install the locked project and development dependencies with uv.
- [x] The installed command exposes version and help output without importing optional providers or performing network or filesystem side effects.
- [x] The distribution includes typing metadata and builds successfully as both a source distribution and wheel.
- [x] Ruff is the sole configured formatter and linter, with the agreed rule families and Python target.
- [x] Pytest, Ruff lint, Ruff format checking, lockfile checking, and package building all pass through documented uv commands.

## Answer

Implemented the installed `agentinstruct` help/version command, side-effect-free
package import, locked development dependencies, Ruff configuration, strict Mypy
checks, contributor documentation, and a CI workflow for the required checks.

Validation on Python 3.13.3: locked sync, lockfile checking, Ruff lint/format,
Mypy, all eight tests, and source/wheel builds passed. A clean copied checkout
installed from the lockfile; an isolated wheel installation passed import,
typing-marker, help, and version checks. Both archives include `py.typed` and
exclude research, prototypes, and local runtime artifacts. Hosted CI execution
is pending the next push.

See [development commands](../../../README.md#development),
[CLI smoke tests](../../../tests/test_cli.py),
[import-safety tests](../../../tests/test_import_safety.py), and the
[implementation map](../map.md).
