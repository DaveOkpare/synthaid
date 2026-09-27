# agentinstruct

A Python framework for generating verified traces from agent interactions.

The package bootstrap is available: an installable typed library, a CLI with
help and version output, and a locked development workflow. Trace generation
and its commands are planned in the [V1 specification](.scratch/v1-agent-trace-generation/spec.md).

## Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```sh
uv sync
uv run agentinstruct --help
uv run agentinstruct --version
```

Python 3.13 or newer is required. `.python-version` selects Python 3.13 for
contributors; uv can install it if it is missing. `uv sync` installs the package
and development dependencies into `.venv`. Commit `uv.lock` with dependency
changes, using `uv add` for runtime dependencies and `uv add --dev` for development
tools. The package currently needs no third-party runtime dependencies.

Run the quality checks from the repository root:

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
```

Ruff is the sole linter and formatter. Apply formatting with `uv run ruff format .`;
apply lint fixes explicitly with `uv run ruff check --fix .`. Mypy checks the
library and tests in strict mode. Run an individual test file while developing
with `uv run pytest tests/test_cli.py`.

CI runs these checks with locked dependencies on Python 3.13. The workflow uses
uv 0.11.26, matching the initialized build backend. `uv build` produces a source
distribution and a wheel in `dist/`, including the `py.typed` marker. Package
contents follow the [uv build backend defaults](https://docs.astral.sh/uv/concepts/build-backend/#file-inclusion-and-exclusion);
research, prototypes, development caches, and generated Runs are outside the
distributed package.

## Project layout

- `src/agentinstruct/`: supported library and CLI code.
- `tests/`: public CLI and import-safety checks, with pytest-asyncio available for
  future asynchronous APIs. Tests do not call external services.
- `.scratch/`: the V1 specification and implementation tickets.
- `CONTEXT.md` and `docs/adr/`: domain vocabulary and architectural decisions.
- `research/` and `prototypes/`: design evidence, outside the runtime package.
