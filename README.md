# agentinstruct

Generate reviewed synthetic data directly in Python through seven imports:
`Task`, `Runner`, `Environment`, `Agent`, `Episode`, `Tool`, and `Judge`.

A Task immediately owns a fresh Episode and UUID. Runner chooses
`output_dir / episode.id / trace.json`, invokes its Environment and collects Episodes.
Environment defines one method, `run()`. The default `UserSimEnv(Environment)`
lets Agents speak in turn, records their messages, then applies an optional final
verifier. Each Agent handles its own optional review and revisions.

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run python examples/direct-dialogue/run.py --output /tmp/agentinstruct-retail
```

The retail example runs offline and reuses Agent and Judge definitions across
independent Tasks. Its checks test structure; they do not establish semantic quality.

## Use Agents and a reusable Judge

Your application owns the inference client around the entire batch. The core
borrows it and never closes it between Tasks, reviews, or verification calls.
Set `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`, and `JUDGE_MODEL` for your server.

```python
import asyncio
import os
from openai import AsyncOpenAI
from agentinstruct import Agent, Judge, Runner, Task
from agentinstruct.judge import Criterion, Rubric


async def main():
    async with AsyncOpenAI(
        base_url=os.environ["MODEL_BASE_URL"],
        api_key=os.environ["MODEL_API_KEY"],
        max_retries=0,
    ) as client:
        correctness = Judge(
            client=client,
            model=os.environ["JUDGE_MODEL"],
            prompt="Check mathematical correctness. Give specific repair feedback.",
            rubric=Rubric((Criterion("correct"),)),
        )
        assistant = Agent(
            os.environ["MODEL_NAME"],
            "Explain the topic with a worked teaching example.",
            reviewer=correctness,
            max_revisions=2,
        )
        user = Agent(os.environ["MODEL_NAME"], "Ask questions about the supplied topic.")
        tasks = [
            Task(
                agents={"assistant": assistant, "user": user},
                input={"topic": topic},
                max_rounds=3,
                verifier=correctness,
            )
            for topic in ("fractions", "decimals")
        ]
        episodes = await Runner(tasks, output_dir="runs", client=client).run()
        for episode in episodes:
            print(episode.verification, episode.messages)


asyncio.run(main())
```

Agent uses Chat Completions. OpenAI SDK 2.30.0 is pinned; generation uses accepted
history and disabled retries. Judge also supports `api="responses"`.
Configure different endpoints with separate application-owned clients, supplied to Agent
or Judge. An Agent's explicit client takes precedence over Runner.client.

Agents can declare Tools for direct generation, but UserSimEnv only supports
conversation messages. It rejects Tool calls, segments and Task deadlines.
Tool execution and other execution policies require a custom Environment.

## Customize generation and scheduling

Generation, evaluation and execution have small structural protocols:

| Seam | Interface | Domain adapter |
| --- | --- | --- |
| agent.Generator | async generate(history, *, client, role, instruction) | Supply a plain object as Agent(generator=...) |
| judge.Evaluator | async evaluate(messages) -> Judgment | Supply it as Agent.reviewer or Task.verifier |
| Environment | async run(task, *, client) -> None | Supply an instance to Runner(environment=...) |

A domain adapter implements these methods without inheriting framework classes.
Generator returns one unreviewed Message. Agent has one public operation:
`generate()` samples, reviews and revises until approved or its revision limit is
exhausted. Its private `_review()` invokes the optional reviewer. UserSimEnv records
the returned Message and passes accepted history to the next Agent.
Reviewer feedback and the current rejected draft reach the generator privately.
The retail example uses a plain generator; tests also demonstrate arithmetic
generation/evaluation and a custom Environment. Supply custom sampling through
`generator=` so it participates in the same review loop. Supporting Message/Tool-call
values live in episode.py, and Judgment lives in judge.py.

Task.agents requires `assistant`; an optional `user` uses the same Agent class.
Only assistant may return `Message(..., control="complete")`. An assistant-only
Task finishes after one response. Dialogue alternates roles, starting with `user`
by default, until completion, `max_rounds` or `max_turns`. Task input is included in
each Agent's context. Construct another Task for another sample; completed Tasks
cannot be reset or rerun.

A callable Judge uses `Judge(check=...)`. Its check receives immutable Messages
and returns a Boolean, Judgment, or ordinary verdict/feedback mapping. Rubrics
require exact Boolean criterion IDs and compute weighted scores locally. A Judge
can serve both review and verification when its criteria suit both uses.
`max_revisions` counts replacement attempts after the initial draft. A rejected
final sample raises `ReviewExhausted` and is never accepted.

Runner assigns each Episode a recording path and calls Environment.run(task, client=...).
UserSimEnv appends each accepted message, then evaluates the optional verifier and
stores its result in memory. Runner saves once per Task, including collected messages
when execution raises or is cancelled, then propagates the error. Earlier Tasks in
the batch are already saved.
Applications own clients, deadlines (for example, `asyncio.timeout`) and any retry policy.

Standalone UserSimEnv runs entirely in memory. Use Runner to persist its traces.
Episode has five ordinary fields: `id`, `messages`, `metadata`, `verification` and
`path`; it has no methods.

Different domains can usually supply a Generator and Evaluator to the default
UserSimEnv. A custom Environment defines its own execution policy and updates the
supplied Episode. Runner owns writing that data to disk.

Generation can also be used directly without a Task or Episode:

```python
from agentinstruct.episode import Message

agent = Agent("model", "Write a worked example.", reviewer=correctness)
reply = await agent.generate([Message("user", "Explain fractions.")], client=client)
```

Use this inside the application's async client scope. `generate()` uses the Agent's
instruction unless history starts with an explicit system instruction. It returns
a reviewed proposal without committing it or executing Tools. Drafts and review
feedback stay local to that call. UserSimEnv records accepted messages.

Task.verifier receives a constructed Judge or an Evaluator, and Agent.reviewer
accepts either. Task data and domain adapters carry no hidden client binding or
resource manager. Custom adapters honor cancellation and keep invocation state
local; their own external dependencies have application-defined lifetimes.

## Optional task files and CLI

```python
from agentinstruct.adapters.task_files import compile_records, load_tasks

tasks = load_tasks("examples/verified-single")
# Ordinary Python input instead of the configured source:
tasks = load_tasks(
    "examples/verified-single", seeds=({"name": n} for n in ["Ada", "Grace"])
)
```

`compile_records` validates and renders without custom imports, inference, or
output files. `load_tasks` constructs the same core objects; model-backed settings
need supplied `client` or named `clients`. JSON, JSONL, CSV, directories, and Python
iterables retain record origins. Invalid records and source-enumeration failures
are distinct. Authored steps still load as Task segments for custom Environments;
UserSimEnv rejects them. The older Tool and stepped examples require a custom
Environment. See [examples](examples/README.md) for the supported conversations.

```sh
uv run agentinstruct validate examples/verified-single --json
uv run agentinstruct run examples/verified-single --output runs/demo --json
uv run agentinstruct inspect runs/demo
uv run agentinstruct inspect runs/demo --tui
uv run agentinstruct export runs/demo --output /tmp/dataset.jsonl
```

CLI run creates an optional manifest alongside Episode directories. Choose a fresh
output root for each CLI batch. CLI model clients use their configured credential
environment variable, defaulting to `OPENAI_API_KEY`.

## Read, inspect, and export

`episode.messages` is an ordinary list of accepted Messages. `episode.verification`
is a Judgment or None. Episode does no judging, history filtering, sealing, loading,
or exporting. Rejected drafts and reviewer feedback remain private to Agent.generate.

Runner writes one JSON snapshot containing `id`, `messages`, `metadata` and
`verification`. It writes and flushes a temporary file beside the destination, then
atomically publishes the trace. Write errors propagate; traces from earlier Tasks
remain intact. An abrupt process termination can lose the current Task's unsaved
messages. The record contains trace data, not live clients.
Message and feedback text are recorded as supplied; there is no automatic redaction.

Read a trace with `json.loads(path.read_text())`. The optional Inspector and CLI
read the same JSON, and CLI export produces message datasets. Exports select passed
verification by default; use `--status unverified` for traces without a verifier.
An absent verification result alone does not distinguish an unfinished run from a
completed run without a verifier.

The former trace format, event ledgers, verification sidecars and `reverify` command
are retired. There is no automatic migration or historical loader.

## Optional vLLM startup

```sh
uv run agentinstruct vllm --model your-model \
  --server-python /path/to/vllm-env/bin/python -- python generate.py
```

`agentinstruct.integrations.vllm.serve.vllm_server(...)` also provides a Python
context manager yielding the ready API URL. It owns and stops its server process
and restores signals. Initialize your separate inference client using that URL.
Core imports and task validation do not start servers or import the vLLM SDK.

See [migration notes](docs/migration-seven-modules.md) for interface changes.
The [library design audit](.scratch/library-design-audit/map.md) preserves historical
measurements and completed refactor records.
