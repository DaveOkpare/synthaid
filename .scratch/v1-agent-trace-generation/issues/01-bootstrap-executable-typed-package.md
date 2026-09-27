# 01: Bootstrap an executable typed package

**What to build:** Establish an installable, typed Python 3.13 library and thin command-line application that contributors can set up, test, lint, format, and build entirely through uv.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Type:** implementation

- [ ] A fresh checkout can install the locked project and development dependencies with uv.
- [ ] The installed command exposes version and help output without importing optional providers or performing network or filesystem side effects.
- [ ] The distribution includes typing metadata and builds successfully as both a source distribution and wheel.
- [ ] Ruff is the sole configured formatter and linter, with the agreed rule families and Python target.
- [ ] Pytest, Ruff lint, Ruff format checking, lockfile checking, and package building all pass through documented uv commands.
