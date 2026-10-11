# File-defined tasks and a local CLI

Status: TOML loading and foreground `validate`/`run` commands are implemented.
The run-management commands and storage extensions below remain proposals.

The first delivery supports a file or directory, named definitions, separate
criterion and step tables, Python tools, and built-in LLM judges. It saves the
JSON exchange, readable `exchange.txt`, and agent logs. Background jobs,
cancellation, resume, and rerun are postponed; manifests, structured
execution events, and run viewing
are also outside this delivery. See the README for the implemented interface.

The intended workflow is to write TOML task definitions, point the CLI at a
file or a directory, and inspect and manage the generated runs. The scope
includes background execution, cancellation, and resuming interrupted work.
TOML is the chosen first format. Keep the parsed schema independent of the
format so YAML can be added later without a second task model.

## Reflection behavior

Preserve the existing policy: stop when evaluation passes, or accept the last
draft when the iteration budget is exhausted. Reflections give drafts chances
to improve; their actual progress should be observable in the saved results.

Keep execution status separate from evaluation outcomes. A completed run can
contain accepted drafts that exhausted their budgets. For each accepted draft,
record `passed`, `budget_exhausted`, or `unevaluated`, together with its attempts
and feedback. These are proposed persisted labels, not new failure conditions.

Keep the existing meaning of `max_iterations`: it limits total evaluated
drafts, including the first one. Three iterations allow up to two revisions.
The budget resets after every accepted draft, including tool-call drafts.

## Capability boundaries

| Module | Responsibility | Depends on |
| --- | --- | --- |
| task-config | Parse, validate, discover, and instantiate task definitions | Existing models, agents, tasks, tools, and evaluators |
| execution-events | Record drafts, evaluations, tool activity, and resumable execution state | Existing agent and environment execution |
| run-store | Persist manifests, checkpoints, events, exchanges, and logs | Execution event and checkpoint contracts |
| job-runner | Schedule batches, own workers, support background jobs, cancellation, and resume | Task config, resumable execution, run store |
| run-viewer | List runs and render exchanges, attempts, and logs | Run store |
| cli | Parse commands and present service results | Config, runner, and viewer interfaces |

The CLI should stay thin. Python callers should be able to load definitions,
start jobs, and read runs through the same underlying modules. Preserve current
`Agent.run()`, `environment.run()`, and export behavior for existing callers.

## Config alternatives

An inline definition per task is easy to read for one task but repeats model,
agent, and rubric settings as examples grow. Named definitions at the top level
allow several tasks to reuse those settings. A Python entry point that builds a
Task keeps maximum flexibility but leaves most of the configuration in code.

Recommend named definitions: `models`, `tools`, `evaluators`, `agents`, and
`tasks`. These are definitions, not shared live Agent objects. Build fresh
agents and LLM judges for every task execution, even when several tasks refer
to the same agent name. Model instances can be shared within a process.

TOML can be read with Python's standard-library `tomllib`. If YAML is added,
use a parser restricted to plain data, then run the same validation pipeline.
Pydantic is already a dependency and can describe the file schema.

Sources: [tomllib](https://docs.python.org/3.13/library/tomllib.html),
[Pydantic models](https://docs.pydantic.dev/latest/concepts/models/),
[PyYAML loading](https://pyyaml.org/wiki/PyYAMLDocumentation).

## Proposed weather definition

This is intended to live at `examples/weather.toml`, with the actual tool
exported as `WEATHER` from `examples/weather_tools.py`.

```toml
schema_version = 1

[models.gpt]
model_name = "openai/gpt-oss-120b"
base_url = "https://api.doubleword.ai/v1"
api_key_env = "DOUBLEWORD_API_KEY"
temperature = 0.7

[tools.weather]
file = "weather_tools.py"
object = "WEATHER"

[evaluators.weather]
kind = "llm"
model = "gpt"

[[evaluators.weather.criteria]]
content = "Applies when the draft calls get_weather or states weather facts: it calls get_weather, or its weather facts match a get_weather result in the conversation."
weight = 1.0

[[evaluators.weather.criteria]]
content = "States weather facts that no get_weather result in the conversation provided."
weight = -1.0

[agents.assistant]
model = "gpt"
instructions = "You are a travel assistant. Use get_weather for every weather fact. Answer in two or three sentences."
tools = ["weather"]
evaluator = "weather"
max_iterations = 3
max_tool_rounds = 10

[agents.traveller]
model = "gpt"
instructions = "You are a traveller planning a trip to Lagos. Write short, casual messages, one question at a time."

[tasks.weather]
assistant = "assistant"
user = "traveller"

[[tasks.weather.steps]]
instruction = "Ask what the weather is like in Lagos today."
max_turns = 2

[[tasks.weather.steps]]
instruction = "Ask whether to pack an umbrella for tomorrow."
max_turns = 1
```

Omit `user` for a single-agent task. Another `[tasks.name]` table adds another
task to the file. Omitting `evaluator` keeps today's acceptance behavior.

Each criterion and step has its own table. Repeating a double-bracket header
adds another item to that ordered list. This gives each item room for longer
text and comments while retaining the same parsed schema as inline tables.

Tools still need Python implementations. Reference a complete `tool.Tool`
object so its schema and function stay together, rather than duplicating the
argument schema in TOML. The same reference type can later support Python
evaluators and Pydantic output classes. A reference has either a config-relative
`file` or an importable `module`, plus an exported `object`; it does not contain
Python expressions. Config parsing does not import those objects. Execution
loads and type-checks the selected references before its first model request.

## Validation and resolution

Parse TOML into plain data, validate typed config, resolve named references,
then instantiate the runtime objects. Use a dedicated config model rather than
changing the existing runtime dataclasses into Pydantic models.

- Reject unsupported schema versions, unknown fields, missing references,
  invalid limits, duplicate criteria, and invalid role combinations.
- Report field paths, such as `agents.assistant.model: unknown model 'gptt'`.
- Resolve hook files relative to the config file, independent of shell cwd.
- Keep API credentials in environment variables. `api_key_env` names a variable;
  omitting it preserves the current `OPENAI_API_KEY` default. Persist the variable
  name, never the resolved credential.
- Keep config schema version separate from the package version.
- For v1, keep instructions and step tables in the task file. Includes,
  inheritance, templates, and environment substitution in arbitrary strings
  are separate extensions.
- Apply the existing tools/structured-output restriction when output-class
  references are introduced.

## File and directory execution

`synthaid run PATH` accepts a single TOML file or a directory. For a directory,
discover immediate `*.toml` files in sorted path order. `--recursive` explicitly
includes subdirectories and excludes hidden directories and the run root.
Preserve task declaration order inside each file.

Validate all discovered definitions before executing any task. An empty
directory or invalid definition is an error. `validate` checks schemas,
references, and hook-file existence without executing hook code or calling a
provider; runtime preflight also resolves selected credentials and hook types.

One invocation creates one job. Each file/task pair creates an independent
child run with fresh agents. Task names are local to their file, so
`weather.toml:weather` and `travel.toml:weather` can coexist. An optional
`--task NAME` selects a task when the input is a single file.

Default to sequential execution. A failed child is saved and the job continues
with the other children. The foreground command returns nonzero when any child
fails. A background submission returns a job ID; its submission exit code does
not claim that the job completed successfully. A future worker-count option can
add bounded parallelism without changing task definitions.

## Proposed command surface

The `validate` and foreground `run` commands below are implemented. Background
execution and the `jobs`/`runs` command groups remain proposals.

```sh
synthaid validate examples/weather.toml
synthaid validate examples/
synthaid run examples/weather.toml --task weather
synthaid run examples/
synthaid run examples/ --recursive --background

synthaid jobs list
synthaid jobs show JOB_ID
synthaid jobs cancel JOB_ID
synthaid jobs resume JOB_ID --background

synthaid runs list --status failed
synthaid runs show RUN_ID
synthaid runs show RUN_ID --attempts
synthaid runs logs RUN_ID --agent assistant
synthaid runs resume RUN_ID
synthaid runs rerun RUN_ID --background
synthaid runs export --status completed --output traces.jsonl
```

Use one `--root` convention across commands, defaulting to `./runs` relative
to the command's cwd. A job stores the absolute root and source paths so a
background worker is not affected by a later cwd change. This keeps output
location out of the task definition: the same experiment can run into a
different store without editing TOML.

Human-readable output is the default; listing, inspection, and validation
commands also support JSON output. Start with a terminal viewer. An interactive
terminal or browser viewer can consume the same saved format later. `argparse`
is sufficient for the initial command hierarchy without a CLI dependency.

Source: [argparse](https://docs.python.org/3.13/library/argparse.html).

## Saved artifacts and job catalog

Keep existing exchange and log formats, and add explicit run metadata:

```text
runs/
  catalog.sqlite
  jobs/<job-id>/
    job.json
    stdout.log
    stderr.log
  <run-id>/
    run.json
    definition.json
    events.jsonl
    checkpoint.json
    exchange.json
    logs/
      assistant.json
      user.json
      assistant-evaluator.json
```

The SQLite catalog tracks jobs, child ownership, leases, and cancellation
requests. Run directories hold portable artifacts. Viewing a saved directory
should remain possible without its original catalog. Existing export-only
directories remain readable with unknown execution/evaluation summaries;
do not infer pass/fail from free-form critiques.

`run.json` records its artifact version, job ID, source file/task, timestamps,
execution status, evaluation counts, and an error summary when applicable.
`definition.json` is the selected task's normalized configuration plus referenced
definitions, including defaults and credential variable names. Store hook-source
fingerprints and package/runtime versions to detect changes before resume.
Persisting configuration supports repeatability; it does not guarantee identical
model replies or external tool results.

`events.jsonl` ties drafts, evaluations, acceptance reasons, requests, and tool
calls to step/turn/attempt identifiers. Persist explicit `passed` and `feedback`;
for the built-in judge also serialize verdict and answered criteria. Its score
and applied threshold can be recorded as diagnostics without adding a required
score field to generic `EvalResult`. Arbitrary custom-evaluator metadata needs
an explicit JSON serialization contract before custom evaluators enter config.

`checkpoint.json` records an event sequence number and enough state to continue
from it. Write checkpoints and manifests atomically. Append and flush events
before advancing the checkpoint. Recovery replays only committed events and
handles an incomplete final JSONL line.

Dataset export selects completed execution by default, including budget-exhausted
drafts. It exports the existing Chat Completions record shape; management metadata
stays in the run artifacts.

## Background jobs, cancellation, and resume

A foreground invocation and a background worker use the same runner. A local
subprocess owns a background job and writes durable status and terminal output.
The CLI uses catalog cancellation requests and process ownership/lease records,
rather than relying on a remembered PID alone. Claim each child run atomically
so two workers or concurrent resume commands cannot execute it together.

Cancellation prevents queued children from starting. An active child stops at
the next execution boundary and saves its state. An in-flight provider request
or Python tool may take time to return; display cancellation as requested until
the worker acknowledges it. Process crashes leave recoverable checkpoints and
expired ownership, with interrupted status determined from that evidence.

Resume continues the same run and retains its ID and history. Rerun creates a
new run from the saved definition and records the original run as its parent.
Resuming a job skips completed children and continues interrupted/cancelled or
failed children from their checkpoints. Missing credentials, changed hook code,
or an incompatible artifact version produce actionable errors before continuation.

The current environment always repeats all steps, so restoring public chat
history alone is insufficient. A resumable execution state needs:

- The selected step, turn, and current speaker/phase.
- Public history and the simulator's private view, including notes and its tools.
- Agent and evaluator logs and their working-history cursors.
- Accepted output and rejected drafts/feedback within an unfinished turn.
- Current reflection iteration, tool-round count, and pending tool-call index.
- Completed tool results and evaluator outcomes, tied to stable event IDs.

Implement resumable execution as an explicit state machine. Existing synchronous
entry points can drive that machine to completion with an in-memory store. File
execution drives it with a durable store and worker controls. Do not reconstruct
working prompts from diagnostic logs, since logs also contain rejected drafts.

Record tool intent before calling Python and its result immediately afterwards.
A crash between those writes leaves an uncertain tool outcome. Resume must
surface that uncertainty and require a declared idempotent retry policy, an
explicit retry choice, or a supplied known result. Saved results are reused;
arbitrary tools must not be silently rerun. A model request whose reply was not
persisted may need to be reissued, which can add another provider request.

## Suggested delivery sequence

1. Config schema, TOML parser, named-reference validation, and file/directory
   discovery. Verify field-path errors and loading independent of cwd.
2. Foreground CLI execution and weather example migration. Verify equivalent
   runtime definitions, fresh agents per child, and batch failure handling.
3. Explicit execution events, run manifests, and list/show/logs/export commands.
   Verify that evaluation exhaustion is visible without changing acceptance.
4. Durable state-machine checkpoints and resume/rerun commands. Verify recovery
   during reflection, between tool calls, and between simulator/assistant turns.
5. Job catalog and background worker lifecycle, cancellation, and batch resume.
   Verify exclusive ownership, child status aggregation, and worker crashes.

All five milestones belong to the requested scope; each produces a separately
testable slice. Test locally with scripted models and controlled tools; keep
provider tests opt-in. Preserve the existing test suite and Python entry points.

The largest change is resumable execution. Config loading and a foreground
command can reuse today's runtime; durable continuation needs additional state
that today's exports intentionally do not capture.
