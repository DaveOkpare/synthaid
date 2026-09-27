# agentinstruct

A Python framework for generating verified traces from agent interactions.

Task Package validation, compilation, deterministic single-Agent and dialogue
generation, and native/OpenAI JSONL export are available through the typed library
and CLI. Further capabilities follow the
[V1 specification](.scratch/v1-agent-trace-generation/spec.md).

## Generate a Trace

Run the [scripted example](examples/scripted-single/task.toml) without network
access or model credentials:

```sh
uv run agentinstruct run examples/scripted-single --output runs --json
```

The `run` command delegates to the same library lifecycle as:

```python
import asyncio
from agentinstruct import Runner, TaskPackage, export_native, load_trace


async def main():
    result = await Runner(output_dir="runs").run(
        TaskPackage.load("examples/scripted-single")
    )
    trace = load_trace(result.traces[0].path)
    print(trace.conversation[0].message.content)
    export_native([result.traces[0].path], "native.jsonl", statuses={"unverified"})


asyncio.run(main())
```

`generate(package, runner=...)` delegates to `Runner.run`; `generate_sync` wraps
the same operation for synchronous scripts. Use the asynchronous API inside an
existing event loop. Both accept a `seed_path` override, equivalent to CLI
`--seed`. `--json` returns the Run identity, ordered Trace references, and all
five terminal status counts. A completed unverified Run exits 0; execution
failures exit 1 and package or Seed validation failures exit 2.

Each execution creates a fresh Run, Trace, Agent, Environment, Interaction,
recorder, and Conversation. `type = "scripted"` Agents consume literal
`responses` strings without calling a Provider. Library callers can supply
`Runner(agent_factory=...)` with a factory accepting an `AgentPlan`; each fresh
Agent implements `async generate(observation)` and returns a `Message` or ordered
list of Messages. The Observation contains the rendered instruction and accepted
history. A custom `environment_factory` may implement asynchronous `setup` and
`run`, with optional `finalize`; it receives an immutable `TaskContext` and Agent
facades that open Interactions. Factories must construct new instances per call.

The local Run directory contains an authoring-file snapshot, manifest, and Trace
index. Each Trace retains its rendered Run Plan, full Seed data and origin,
accepted Message Commits, separate execution Events, component references and
available source digests, timing, and generation outcome. A complete `trace.json`
is persisted before its index reference is published. `load_trace` returns an
immutable snapshot; native JSONL export reads these persisted snapshots and
needs no live Runner or original package.

Verification is not implemented yet, so successful generation is **unverified**
with a separate `terminated` generation outcome. Export requires explicit selection
of `unverified` or other non-accepted statuses; its default selects only accepted
Traces. Live model adapters, tools, and review arrive in later tickets. Current
generation handles one JSON-object Seed per Run.

## Generate and export a dialogue

The [scripted dialogue](examples/scripted-dialogue/task.toml) runs without network
access or credentials:

```sh
uv run agentinstruct run examples/scripted-dialogue --output runs --json
```

Set `[environment]` to `type = "dialogue"` and declare exactly the `user` and
`assistant` Agents, each with an explicit `target` Boolean. Exactly one must be
the Target Agent; either participant can be the target. `initiator` selects the
opening participant (default `user`), after which the Environment alternates
Interactions. Both participants observe the full accepted shared Conversation
in occurrence order. Relaying a reply references its existing Message Commit.

`max_rounds` defaults to 10 and bounds pairs of participant turns: at most twice
that many Interactions, regardless of initiator or Messages per Action. Reaching
the cap produces `truncated/max_rounds`. An optional positive `timeout_seconds`
bounds setup and generation together, and grants finalization its own equal
timeout. A framework deadline produces `truncated/timeout`; accepted partial
history stays in the Trace. Agent or Environment exceptions produce `failed`.

For the current single-step dialogue, the target can return
`Message(role="assistant", content="Done.", control="complete")`. The completion
proposal takes effect only after that Message is accepted and persisted, producing
`terminated/completed`, even on the last allowed turn. A scripted target may use
`{ content = "Done.", control = "complete" }` in its `responses` array. Plain text
and script exhaustion never signal completion; exhaustion fails the Trace. This
interim Message control will evolve into reviewed framework control Tool calls
with Task Steps in ticket 09. The single-Agent Environment completes after its
one accepted Interaction.

Export one or more persisted Trace directories (or `trace.json` paths) returned
by `run`:

```sh
uv run agentinstruct export runs/<run-id>/traces/<trace-id> \
  --format openai --status unverified --output dialogue.jsonl
```

`--format native` exports complete Trace snapshots. Both formats select only
`accepted` by default; repeat `--status` to explicitly select other statuses.
`--json` reports the exported count. OpenAI JSONL contains one `messages` array
per nonempty selected Trace: Target Agent replies map to `assistant`, and shared
replies from the other participant map to `user`. Native IDs, control metadata,
and Events stay out of training Messages. The Python equivalent is
`export_openai(trace_paths, "dialogue.jsonl", statuses={"unverified"})`.

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

The current implementation supports schema version `"1"`, a `single` or `dialogue`
Environment, exactly one explicit Target Agent, the `local` Runtime, and a JSON
object Seed. Every Agent requires `agents/<id>/instruction.md`. Unknown configuration
fields and unsupported component selections fail validation. Multi-step Tasks,
collections, tools, review, and verification arrive in later
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
The compiler prepares inputs for one Trace attempt; the Runner assigns
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
- `tests/`: public Runner lifecycle, persisted export, CLI, and import-safety
  checks. Tests use deterministic extensions and do not call external services.
- `.scratch/`: the V1 specification and implementation tickets.
- `CONTEXT.md` and `docs/adr/`: domain vocabulary and architectural decisions.
- `research/` and `prototypes/`: design evidence, outside the runtime package.
