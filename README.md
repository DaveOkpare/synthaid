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
            prompt="Evaluate the criteria carefully and give specific repair feedback.",
            rubric=Rubric(
                [Criterion("The mathematics is correct.")],
                threshold=0.9,
            ),
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
                agents={"user": user, "assistant": assistant},
                input={"topic": topic},
                max_turns=6,
                verifier=correctness,
            )
            for topic in ("fractions", "decimals")
        ]
        episodes = await Runner(tasks, output_dir="runs", client=client).run()
        for episode in episodes:
            print(episode.verification, episode.messages)


asyncio.run(main())
```

Agent and Judge use the Responses API. The configured server must support
`/v1/responses`. OpenAI SDK 2.30.0 is pinned. Agent uses the supplied client
and its configured retry policy.
Configure different endpoints with separate application-owned clients, supplied to Agent
or Judge. An Agent's explicit client takes precedence over Runner.client.

Agents can declare Tools for direct generation, but UserSimEnv only supports
conversation messages. It rejects Tool calls.
Tool execution and other execution policies require a custom Environment.

Tool holds an async function, its `id`, `description` and `input_schema`.
`schema()` returns the Responses function schema; `call(arguments)` awaits
the function with the supplied argument mapping and returns its result unchanged.
The ID defaults to the function name. Validation and error handling belong in the
function when needed; exceptions propagate directly.

## Customize generation and scheduling

Agent calls the OpenAI SDK directly. Set its model, instruction, tools, optional
reviewer and revision limit. `generate()` makes one request, then optionally
reviews and revises the result. Each Agent owns a private `history`. Pass only new
messages to `generate()`; it appends them and retains its outputs and review
feedback for subsequent turns. It returns the native SDK response, preserving
text, tool calls, status and other API fields. Additional request options go directly
to the SDK through `generate(..., **options)`, including `reasoning` and `text.format`
for reasoning summaries and structured output on compatible models. Reasoning summaries
are distinct from raw internal reasoning, which OpenAI does not expose
([reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)).
Generation is non-streaming.

`Message` is a small `TypedDict` with `role` and `content`:

```python
from agentinstruct.episode import Message

message = Message(role="user", content="Hello")
```

It is an ordinary OpenAI-format dictionary at runtime, with type checking for
text conversation messages. Episode stores `list[Message]`. Agent and Judge
also accept native API mappings for tool calls and multimodal content.
There are no `actor_id` or `control` fields, conversion methods, or custom
FunctionCall/ToolCall wrappers.

Evaluation and execution have small structural protocols:

| Seam | Interface | Usage |
| --- | --- | --- |
| judge.Evaluator | async evaluate(messages) -> Judgment | Agent.reviewer or Task.verifier |
| Environment | async run(task, *, client) -> None | Runner(environment=...) |

Task.agents requires `assistant`; an optional `user` uses the same Agent class.
An assistant-only Task finishes after one response. Agents take turns in dictionary
insertion order: `{"user": user, "assistant": assistant}` starts with the user.
Dialogue ends at `max_turns` (20 messages by default). UserSimEnv records the role
from Task.agents. On each turn it passes only the last published Episode message
as a user message. Each Agent keeps its own earlier context, including private
tool calls, tool results and review feedback. Only the reply text is published
to the Episode and made available to the other Agent.

Task is a small dataclass holding `agents`, `input`, `verifier`, `max_turns` and an
automatically created `episode`. Task copies each supplied Agent with a fresh
history, including when the same configuration is used for both participants or
across Tasks. Clients, Tools and reviewers remain shared as configured. Inspect
`task.agents[role].history` for that participant's private context.
Input is added once on each Agent's first turn and saved in `episode.metadata["input"]`.
Add other trace metadata directly to `episode.metadata`. Construct another Task
for another sample; Runner rejects an existing output directory.

Judge takes a Rubric and either a model/client or a `check=` callback.
`Criterion(context, weight=1.0)` describes
one condition; `Rubric(criteria, threshold)` holds a list of these conditions and an
explicit threshold. Supply a nonempty list with positive weights. Evaluation returns
one pass/fail grade per criterion and optional feedback. Judge computes
`score = sum(weights of passed criteria) / sum(all weights)` and returns
`Judgment(passed=score > threshold, feedback=..., score=...)`. Equality rejects;
a threshold of 1.0 therefore never accepts. There are no criterion IDs,
evidence records or Judge-specific timeout/error policies.
A Judge can serve both review and verification when its criteria suit both uses.
For model evaluation, `prompt="..."` replaces the default grading instructions.
The rubric's criterion contexts and the messages are supplied with every request.

For code evaluation, pass a synchronous or asynchronous function. It receives the
messages and returns `{"criteria": [True, False, ...], "feedback": "..."}` in rubric
order; feedback can be omitted. Supplying `check=` uses that function without a model
request. Judge still computes the score and acceptance:

```python
judge = Judge(
    Rubric([Criterion("The conversation includes an assistant reply.")], 0.9),
    check=lambda messages: {
        "criteria": [any(m.get("role") == "assistant" for m in messages)]
    },
)
```

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

Different domains can supply instructions and an Evaluator to UserSimEnv.
A custom Environment defines its own execution policy and updates the supplied
Episode. Runner owns writing that data to disk.

Generation can also be used directly without a Task or Episode:

```python
agent = Agent("model", "Write a worked example.", reviewer=correctness)
reply = await agent.generate(
    [{"role": "user", "content": "Explain fractions."}], client=client, temperature=0.2
)
print(reply.output_text)
```

Use this inside the application's async client scope. `generate()` uses the Agent's
instruction unless its initial history starts with an explicit system or developer
instruction. Direct calls continue the same conversation; use separate Agents for
independent conversations. `generate()` returns a reviewed SDK response and retains
it in the Agent's private history. Drafts and review feedback stay with that Agent.
Rejected tool proposals are included as JSON text
when requesting a revision, so no pending tool call requires execution.
UserSimEnv records accepted conversation text.

Task.verifier receives a constructed Judge or an Evaluator, and Agent.reviewer
accepts either. Task data and domain adapters carry no hidden client binding or
resource manager. Custom adapters honor cancellation; their external dependencies have
application-defined lifetimes.

## Optional task files and CLI

```python
from agentinstruct.adapters.task_files import compile_records, load_tasks

tasks = load_tasks("examples/verified-single", client=client)
# Ordinary Python input instead of the configured source:
tasks = load_tasks(
    "examples/verified-single", seeds=({"name": n} for n in ["Ada", "Grace"]), client=client
)
```

`compile_records` validates and renders without custom imports, inference, or
output files. `load_tasks` constructs the same core objects; model-backed settings
need supplied `client` or named `clients`. JSON, JSONL, CSV, directories, and Python
iterables retain record origins. Invalid records and source-enumeration failures
are distinct. Agent table order determines turn order. Task files reject removed
scripted/custom generators, steps, `max_rounds`, `initiator` and environment deadlines; use `max_turns` for the
conversation limit. Record provenance is placed in Episode metadata.
See [examples](examples/README.md) for the supported conversations.

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

`episode.messages` is an ordinary list of accepted OpenAI message dictionaries. `episode.verification`
is a Judgment or None. Episode does no judging, history filtering, sealing, loading,
or exporting. Rejected drafts and reviewer feedback remain in the owning Agent's
private history.

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

Inspector accepts a trace file, an Episode directory, or a batch directory.
Its four views are `summary`, `conversation`, `verification`, and `metadata`.
For example, `agentinstruct inspect runs/demo --trace 1 --view verification`
shows the saved Judge verdict, score and feedback for the first trace.
Conversation shows published role/content messages; private Agent histories are
not saved in the Episode. `--json` returns the selected view as JSON.

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
