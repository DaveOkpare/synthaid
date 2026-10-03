# agentinstruct

Generate reviewed synthetic data directly in Python through seven imports:
`Task`, `Runner`, `Environment`, `Agent`, `Episode`, `Tool`, and `Judge`.

A Task immediately owns a fresh Episode and UUID. Runner opens recording at
`output_dir / episode.id`, invokes its Environment and collects the Episodes.
Environment owns execution and finalization. The default UserSimEnv executes
ordered segments, seals generation and applies the optional final verifier.
Each Agent owns its Tools and optional reviewer.

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked
uv run python examples/direct-dialogue/run.py --output /tmp/agentinstruct-retail
```

The retail example runs offline and reuses Agent and Judge definitions across
independent Tasks. Its checks test structure; they do not establish semantic quality.

## Use a model, Tool, and reusable Judge

Your application owns the inference client around the entire batch. The core
borrows it and never closes it between Tasks, reviews, or verification calls.
Set `MODEL_BASE_URL`, `MODEL_API_KEY`, `MODEL_NAME`, and `JUDGE_MODEL` for your server.

```python
import asyncio
import os
from openai import AsyncOpenAI
from agentinstruct import Agent, Environment, Episode, Judge, Runner, Task, Tool
from agentinstruct.judge import Criterion, Rubric


async def lookup(arguments):
    return {"topic": arguments["topic"], "denominator": "equal parts of a whole"}


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
            "Write a worked teaching example. Use lookup when helpful.",
            tools=[Tool(lookup)],
            reviewer=correctness,
            max_revisions=2,
        )
        tasks = [
            Task(
                agents={"assistant": assistant},
                input={"topic": topic},
                segments=[
                    {
                        "name": "draft",
                        "instructions": {"assistant": "Draft an example."},
                    },
                    {
                        "name": "revise",
                        "instructions": {"assistant": "Check the earlier example."},
                    },
                ],
                verifier=correctness,
                timeout_seconds=120,
            )
            for topic in ("fractions", "decimals")
        ]
        identity = tasks[0].episode.id
        episodes = await Runner(tasks, output_dir="runs", client=client).run()
        episode: Episode = episodes[0]
        assert episode is tasks[0].episode and episode.id == identity
        print(episode.status, episode.messages)


asyncio.run(main())
```

Use `api="responses"` on Agent/Judge for the Responses API; the default is Chat
Completions. OpenAI SDK 2.30.0 is pinned. Both surfaces use stateless accepted
history, disabled retries, and local strict JSON/schema checks. Configure different
endpoints with separate application-owned clients, supplied explicitly to Agent
or Judge. An Agent's explicit client takes precedence over Runner.client.

Tool functions receive one immutable arguments mapping. `input_schema` and
`output_schema` validate JSON locally. Execution failures fail by default;
`execution_errors="result"` returns a safe error record. Invalid arguments and
results always fail. `output_schema` on Agent accepts a strict JSON Schema or a
Pydantic model class, including nested aliases, enums, nullable fields, and dates.

## Customize generation and scheduling

Generation, evaluation and execution have small structural protocols:

| Seam | Interface | Domain adapter |
| --- | --- | --- |
| agent.Generator | async generate(history, *, client, role, instruction) | Supply a plain object as Agent(generator=...) |
| judge.Evaluator | async evaluate(messages) -> Judgment | Supply it as Agent.reviewer or Task.verifier |
| Environment | async run(task, *, client) -> None | Supply an instance to Runner(environment=...) |

A domain adapter implements these methods without inheriting framework classes.
Generator returns one Message or a nonempty sequence. Agent still performs review,
revision, durable acceptance and approved Tool execution around that result.
Reviewer feedback and the current rejected draft reach the generator privately.
The retail example uses a plain generator; tests also demonstrate arithmetic
generation/evaluation and a custom Environment. Existing Agent.generate subclass
overrides remain usable. Supporting Message/Tool-call values live in episode.py,
and Judgment lives in judge.py.

Task.agents requires `assistant`; an optional `user` uses the same Agent class.
Only assistant may return `Message(..., control="complete")`. An assistant-only
segment finishes after its turn; dialogue uses completion or configured limits.
Segment instruction additions replace the previous additions while retaining the
base instruction and accepted/private history. Construct another Task for another
sample; completed Tasks cannot be reset or rerun.

A callable Judge uses `Judge(check=...)`. Its check receives immutable Messages
and returns a Boolean, Judgment, or ordinary verdict/feedback mapping. Rubrics
require exact Boolean criterion IDs and compute weighted scores locally. A Judge
can serve both review and verification when its criteria suit both uses.
`max_revisions` counts replacement attempts after the initial draft. An opted-in
exhaustion fallback accepts only ordinary text, with recorded evidence.

Runner opens each existing Episode and calls Environment.run(task, client=...).
The Environment owns beginning execution, deadlines, outcomes, sealing and final
verification. The default UserSimEnv implements these safeguards; it also works
standalone after you open task.episode. Application entry points own clients and
other contexts around the batch.

Different domains can usually supply a Generator and Evaluator to the default
UserSimEnv. A custom Environment defines its own execution policy. Runner forwards
its errors and leaves finalization to that implementation. For example, inside
your async entry point:

```python
class CustomDomain:
    async def run(self, task: Task, *, client=None) -> None:
        task.episode.add_secrets(client)
        task.episode.begin(task.declaration())
        async with asyncio.timeout(task.timeout_seconds):
            await task.agents["assistant"].turn(task.episode, client=client)
        task.episode.seal()
        if task.verifier is not None:
            await task.episode.verify(task.verifier)


environment: Environment = CustomDomain()
episodes = await Runner(
    tasks, output_dir="runs", client=client, environment=environment
).run()
```

This minimal custom example propagates execution errors; a domain implementation
can record its own failure outcomes. UserSimEnv records failures/cancellation and
preserves partial evidence. Runner adds no lifecycle wrapper.

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
are distinct. Authored steps become segments of one Task and Episode per input.

```sh
uv run agentinstruct validate examples/verified-single --json
uv run agentinstruct run examples/verified-single --output runs/demo --json
uv run agentinstruct inspect runs/demo
uv run agentinstruct inspect runs/demo --tui
uv run agentinstruct export runs/demo --output /tmp/dataset.jsonl
uv run agentinstruct reverify runs/demo/<episode-id> --package examples/verified-single
```

CLI run creates an optional manifest alongside Episode directories. Choose a fresh
output root for each CLI batch. CLI model clients use their configured credential
environment variable, defaulting to `OPENAI_API_KEY`.

## Read, inspect, and export

`episode.messages` is the read-only accepted conversation. Drafts, reviews,
reasoning evidence, and execution errors are recorded separately. Tool exchanges
are private to their calling Agent; peers and default training exports exclude
them. Exports select assistant as the training target and preserve accepted user
context. CLI exports select accepted Episodes by default; use `--status unverified`
when appropriate, or `--verification ID` to select an immutable judgment.

`Episode.load(path)` reads current and historical Trace JSON without importing
original components. `await episode.verify(judge)` appends a sidecar after sealing
and leaves generation bytes unchanged. Failed or invalid generation cannot become
accepted. Without a verifier, status remains unverified. Limits and deadlines are
recorded in `episode.generation`; failed final judging records an unverified attempt.

## Optional vLLM startup

```sh
uv run agentinstruct vllm --model your-model \
  --server-python /path/to/vllm-env/bin/python -- python generate.py
```

`agentinstruct.integrations.vllm.serve.vllm_server(...)` also provides a Python
context manager yielding the ready API URL. It owns and stops its server process
and restores signals. Initialize your separate inference client using that URL.
Core imports and task validation do not start servers or import the vLLM SDK.

See [migration notes](docs/migration-seven-modules.md) for interface changes and
[the Runner correction report](.scratch/deep-modules/runner-correction.md) for
measured changes and verification.
