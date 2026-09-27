# agentinstruct

A Python framework for generating verified traces from agent interactions.

Task Package validation and compilation are available through the typed library
and CLI. Trace generation is planned in the
[V1 specification](.scratch/v1-agent-trace-generation/spec.md).

## Validate a Task Package

The [single-agent example](examples/single-agent/task.toml) contains `task.toml`,
one JSON Seed, and `agents/assistant/instruction.md`. Validate it without model
calls or credentials:

```sh
uv run agentinstruct validate examples/single-agent
uv run agentinstruct validate examples/single-agent --json
uv run agentinstruct validate examples/single-agent --seed /path/to/seed.json
```

`--json` emits the compiled Run Plan on success and a structured validation error
on failure. Validation failures exit with status 2. The default Seed path is
relative to the Task Package; an explicit `--seed` override is relative to the
working directory. Validation reads inputs without creating Run outputs.

The equivalent Python API is:

```python
from agentinstruct import TaskPackage

package = TaskPackage.load("examples/single-agent")
plan = package.compile()  # Or package.compile(seed_path="/path/to/seed.json")
print(plan.agents["assistant"].base_instruction)
print(plan.digest)
print(plan.to_json())
```

This initial slice supports schema version `"1"`, a single Agent with explicit
`target = true`, a `single` Environment, the `local` Runtime, and a JSON object
Seed. Every Agent requires `agents/<id>/instruction.md`. Unknown configuration
fields and unsupported component selections fail validation. Multi-step Tasks,
collections, tools, review, verification, and runtime execution arrive in later
tickets.

`[variables]` maps template aliases to dot paths through nested JSON mappings.
Array indexing and empty path segments are unsupported. Every selector must
resolve, and instruction templates use strict, sandboxed Jinja. Templates may
interpolate JSON values; Python methods and other runtime attributes are rejected
(use Jinja filters such as `name | upper`). Iterator filters produce data lists,
and the nondeterministic `random` filter is unavailable. A `[seed]`
`id_variable` names a declared alias containing a nonempty string or integer;
otherwise the Seed ID is its canonical content hash.

`[model]` supplies the provider identifier, model name, and optional `temperature`
and `max_tokens`; an Agent's `[agents.<id>.model]` may override those fields.
Provider declarations support `openai`, `openai-compatible`, and `vllm` identities
for compilation only. They are not a claim of implemented runtime adapters.
OpenAI defaults to the `responses` API surface; the other types default to
`chat_completions`. An explicit `api` selects either surface. Credentials use
`api_key_env` references, never inline values. Validation neither reads those
environment variables nor imports providers. Connection URLs cannot contain
credentials, query strings, or fragments.

Run Plans separate Task identity, Seed data and origin, extracted Variables,
Provider and Agent settings, Environment, Runtime, and provenance. Their nested
data is immutable; `to_dict()` returns an independent JSON-compatible copy.
Digests use canonical sorted JSON and exclude generated execution identities.
The compiler prepares inputs for one Trace attempt; the future Runner assigns
fresh Run and Trace IDs when executing them. Keep credentials out of Seed data
and instructions, which are intentionally retained as Task inputs.

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
tools. Jinja supplies instruction templating and Pydantic validates configuration.

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
- `tests/`: public API, CLI, and import-safety checks, with pytest-asyncio available for
  future asynchronous APIs. Tests do not call external services.
- `.scratch/`: the V1 specification and implementation tickets.
- `CONTEXT.md` and `docs/adr/`: domain vocabulary and architectural decisions.
- `research/` and `prototypes/`: design evidence, outside the runtime package.
