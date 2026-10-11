# synthaid

Generate synthetic conversations with LLM agents, tools, and draft evaluation.
An optional user simulator drives the conversation. Evaluators give agents
feedback to revise their drafts; the final exchange and detailed logs can be
saved for training or inspection.

[Get started](#get-started) · [Python API](#python-api) ·
[Evaluators and reflection](#evaluators-and-reflection) ·
[Tools](#tools) · [Structured output](#structured-output) ·
[TOML](#toml) · [CLI](#cli) · [Results](#results) · [Errors](#errors)

## Get started

Requires Python 3.13 or newer. From a source checkout, install with uv:

```sh
git clone https://github.com/DaveOkpare/synthaid.git
cd synthaid
uv sync
```

Alternatively, run `python -m pip install .` in the checkout to install into
an existing Python environment. You can then use `synthaid` directly instead
of `uv run synthaid`.

The bundled weather example uses Doubleword and a Python tool with made-up
forecasts. Set your provider key, validate the definitions, then run them:

```sh
export DOUBLEWORD_API_KEY="your-api-key"
uv run synthaid validate examples/weather.toml
uv run synthaid run examples/weather.toml
```

Validation makes no model requests and needs no credentials. Running prints
status and a saved directory containing `exchange.txt`, `exchange.json`, and
logs. Credentials are read from the environment; `.env` files are not loaded
automatically.

## Supported implementations

| Component | Python API | TOML |
| --- | --- | --- |
| Model | `model.Model`, using a Chat Completions endpoint | Named connection settings under `models` |
| LLM agent | `agent.Agent` | Named definition under `agents`; LLM is implicit |
| LLM evaluator | `evaluation.LLMJudge` | `evaluators.NAME` with `kind = "llm"` |
| Python evaluator | A callable taking `Draft` and returning `EvalResult` | Not supported yet |
| Python tool | `tool.Tool` wrapping a function and its argument schema | A `file` or `module` reference to an exported `Tool` |
| Structured output | A Pydantic model class passed as `output_type` | Not supported yet |

Assistant and user simulator are roles assigned by a task. Both use `Agent`.
`LLMJudge` is also an agent, specialized for evaluation. Each agent accepts
one evaluator. Models can be shared; give each conversation fresh agents and
judges because they keep state and logs.

Only evaluator definitions currently accept `kind`, and its only supported
value is `"llm"`. Agents and tools do not accept a `kind` field yet.

The endpoint and selected model must support the features you use: Chat
Completions for text, function calling for tools, and structured output for
Pydantic replies and LLM judges. synthaid does not check provider capabilities
before making a request.

## Python API

This complete example generates a conversation with a user simulator and
an LLM judge, then saves it:

```python
import os

from synthaid import agent
from synthaid import environment
from synthaid import evaluation
from synthaid import export
from synthaid import model
from synthaid import task

gpt = model.Model(
    model_name="openai/gpt-oss-120b",
    base_url="https://api.doubleword.ai/v1",
    api_key=os.environ["DOUBLEWORD_API_KEY"],
)
judge = evaluation.LLMJudge(
    gpt,
    [evaluation.Criterion(content="Answers the question asked.")],
)
assistant = agent.Agent(gpt, "You are a travel assistant.", evaluator=judge)
traveller = agent.Agent(gpt, "You are a traveller planning a trip to Lagos.")
trip = task.Task(
    assistant,
    [
        task.Step("Ask what to see in Lagos.", max_turns=2),
        task.Step("Ask about the best time of year to visit."),
    ],
    user=traveller,
)

environment.run(trip)
directory = export.save(trip, "runs")
print(directory)
```

`Model(model_name, base_url, api_key=None, temperature=0.7)` works with
servers that implement Chat Completions. Omitting `api_key` lets the OpenAI
SDK read `OPENAI_API_KEY`.
`Model.generate(messages, *, tools=(), output_type=str)`
makes one generation call, returns an assistant `Message`, and leaves tool
execution and reflection to the agent. Transport retries come from the SDK.

`Agent(model, instructions, ...)` accepts these optional settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `output_type` | `str` | Text, or a Pydantic model class for structured output |
| `tools` | `()` | Tools available to the model; names must be unique |
| `evaluator` | `None` | Checks each draft; absent means every draft is accepted |
| `max_iterations` | `3` | Maximum evaluated drafts per accepted draft, including the first |
| `max_tool_rounds` | `10` | Maximum accepted batches of tool calls per turn |

Both limits must be at least 1. Tools cannot be combined with a Pydantic
`output_type`.

A `Task(assistant, steps, user=None, chat_history=[])` needs at least one
`Step(instruction, max_turns=1)`. Its user and assistant must be different
agent instances. Steps build on the same conversation:

- With a simulator, the instruction is private to that simulator. Each step
  adds `max_turns` user/assistant exchanges, with the simulator speaking first.
- Without a simulator, each instruction is sent directly as a user message.
  Each step gets one assistant turn; `max_turns` is ignored.

`environment.run(task)` updates `task.chat_history` in place and returns
`None`. You can supply starting history without system messages. Calling
`run()` again repeats all steps on top of the existing history; it is not a
resume operation. Saving is explicit for Python callers.

For a single turn without a task, using the same model:

```python
from synthaid import message

helper = agent.Agent(gpt, "You are a travel assistant.")
replies = helper.run([message.Message("user", "What should I see in Lagos?")])
print(replies[-1].text)
```

`Agent.run(messages)` adds its own system instructions, so the input must
not contain system messages. It returns the accepted messages added by that
turn: tool-call drafts, their tool results, and the final reply.
`Agent.logs` returns a copy of its full log, including rejected drafts and
feedback.

### Messages

`Message(role, content, reasoning=None, tool_calls=(), tool_call_id=None)`
represents every message. Roles are `"system"`, `"user"`, `"assistant"`, and
`"tool"`. Content is a string, a Pydantic instance, or `None`. Tool requests
are `ToolCall(id, name, arguments)` objects attached to assistant messages;
`arguments` is a dictionary. A tool result carries the matching call ID.

`Message.text` returns text, JSON for structured content, or an empty string
for missing content. `to_chat_completions()` and `from_chat_completions()`
convert between these objects and SDK messages. Model reasoning, when supplied
as `reasoning_content`, is retained in history and JSON logs but never sent
back to a model.

## Evaluators and reflection

An evaluator is a callable taking `agent.Draft` and returning
`evaluation.EvalResult`.

`Draft.message` is the candidate reply, including any tool calls.
`Draft.context` is the history supplied to that agent plus this turn's
accepted drafts and tool results. It excludes reflection attempts, feedback,
and the agent's system instructions. An assistant's evaluator sees the public
conversation; a simulator's evaluator also sees its private step notes.
Evaluators check tool-call drafts as well as final replies.

`EvalResult(feedback, *, passed, metadata={})` contains the decision, feedback
to use on failure, and optional details. For example, this Python evaluator
checks a character limit using the `gpt` model from the Python example:

```python
def concise(draft: agent.Draft) -> evaluation.EvalResult:
    length = len(draft.message.text)
    return evaluation.EvalResult(
        "Keep the reply within 280 characters.",
        passed=length <= 280,
        metadata={"characters": length},
    )


short_writer = agent.Agent(gpt, "Answer clearly.", evaluator=concise)
```

### LLM judges

`LLMJudge(model, criteria, instructions=..., threshold=None)` checks drafts
using structured output. Its default instructions provide the judging prompt;
you may replace them. It has no tools or evaluator of its own.

Each `Criterion(content=..., weight=1.0)` describes something to detect. Contents
must be unique and the list must be nonempty. Use positive weights for desired
behavior and negative weights for unwanted behavior:

```python
judge = evaluation.LLMJudge(
    gpt,
    [
        evaluation.Criterion(content="Answers the question asked."),
        evaluation.Criterion(content="Repeats the same sentence.", weight=-1.0),
    ],
)
```

The judge returns an `Answer(content=..., met=...)` for each criterion, in order,
and a `Verdict(answers=..., feedback=...)`. `met` is `Met.YES` (`"yes"`), `Met.NO`
(`"no"`), or `Met.NA` (`"n/a"`). For a negative criterion, `"yes"` means the
unwanted behavior is present. Weights stay in Python and are not sent to the
judge.

The score is the sum of weights whose answer is `"yes"`. A draft passes when
that score reaches the threshold. The default threshold is the sum of positive
weights whose answer is not `"n/a"`: all applicable positive criteria must be
met and no negative criterion may be met. An explicit `threshold` replaces
that rule. `result.metadata["verdict"]` holds the raw verdict;
`result.metadata["criteria"]` holds criteria with their weights and answers.

### Reflection behavior

For each draft, the agent evaluates and stops early when it passes. On
failure, the draft and feedback go back to the model for another attempt.
`max_iterations = 3` allows the first draft and up to two revisions. When
all attempts fail, the last draft is still accepted.

Accepted tool calls execute, their results enter the conversation, and the
next draft gets a fresh reflection budget. One accepted draft with any number
of tool calls counts as one tool round. Feedback from rejected drafts is
kept in logs but dropped from subsequent requests once a draft is accepted.

Reflection offers chances to improve; it does not guarantee a passing final
reply. A completed CLI run means execution completed, even if drafts exhausted
their evaluation budgets.

## Tools

A tool keeps its function and argument schema together. This example uses
made-up weather data and the `gpt` model defined above:

```python
from synthaid import tool


def get_weather(city: str) -> dict[str, str]:
    return {"city": city, "forecast": "31°C, humid, clear"}


weather = tool.Tool(
    name="get_weather",
    description="Gets a city's weather forecast.",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
    function=get_weather,
)
weather_assistant = agent.Agent(
    gpt, "Use get_weather for weather questions.", tools=[weather]
)
```

Functions receive the model's arguments as keyword arguments. Return a
string or a JSON-serializable value; non-string values are encoded as JSON.
The schema is sent to the model; synthaid does not validate arguments against
it locally. Tool failures raise errors rather than being returned to the model
as feedback. The simulator may also have tools; its calls and results stay in
its private logs and do not appear in the public exchange. The simulator sees
the assistant's final replies, without the assistant's tool activity.

## Structured output

Pass a Pydantic model class as `output_type` to receive a validated instance.
Using `gpt` from the Python example:

```python
import pydantic

from synthaid import message


class Destination(pydantic.BaseModel):
    city: str
    country: str


extractor = agent.Agent(
    gpt, "Extract the destination.", output_type=Destination
)
reply = extractor.run(
    [message.Message("user", "I am visiting Lagos, Nigeria.")]
)[-1]
assert isinstance(reply.content, Destination)
print(reply.content.city)
```

`reply.content` retains the instance; `reply.text` and saved JSON records
represent it as JSON. Structured output requires provider support, cannot be
combined with tools, and is currently available through Python only.

## TOML

A file defines named models, agents, tools, evaluators, and tasks. Definitions
can be reused by multiple tasks; each build creates fresh agents and judges.
Names are local to that file. This is a complete task definition:

```toml
schema_version = 1

[models.gpt]
model_name = "openai/gpt-oss-120b"
base_url = "https://api.doubleword.ai/v1"
api_key_env = "DOUBLEWORD_API_KEY"

[evaluators.quality]
kind = "llm"
model = "gpt"

[[evaluators.quality.criteria]]
content = "Answers the question asked."

[agents.assistant]
model = "gpt"
instructions = "You are a travel assistant."
evaluator = "quality"

[agents.traveller]
model = "gpt"
instructions = "You are planning a trip to Lagos. Ask short questions."

[tasks.trip]
assistant = "assistant"
user = "traveller"

[[tasks.trip.steps]]
instruction = "Ask what to see in Lagos."
max_turns = 2

[[tasks.trip.steps]]
instruction = "Ask about the best time of year to visit."
```

Save it as `trip.toml` and run `uv run synthaid run trip.toml`. Omit `user`
for direct prompts. Another `[tasks.NAME]` table adds a task. Each criterion
and step gets its own `[[...]]` table, preserving declaration order.

### Field reference

| Table | Required fields | Optional fields and defaults |
| --- | --- | --- |
| Root | `schema_version = 1`, nonempty `models`, `agents`, and `tasks` | `tools` and `evaluators` default to empty tables |
| `models.NAME` | `model_name`, `base_url` | `api_key_env = "OPENAI_API_KEY"`, `temperature = 0.7` |
| `agents.NAME` | `model`, `instructions` | `tools = []`, no `evaluator`, `max_iterations = 3`, `max_tool_rounds = 10` |
| `tools.NAME` | `object`, exactly one of `file` or `module` | None |
| `evaluators.NAME` | `kind = "llm"`, `model`, nonempty `criteria` | Default judge `instructions`; `threshold` calculated per verdict |
| `evaluators.NAME.criteria` | `content` | `weight = 1.0` |
| `tasks.NAME` | `assistant`, nonempty `steps` | No `user` simulator |
| `tasks.NAME.steps` | `instruction` | `max_turns = 1` |

`model`, `tools`, `evaluator`, `assistant`, and `user` reference definitions
by name. Unknown fields, unknown references, duplicate criterion contents,
duplicate tool references, and limits below 1 are rejected. The user and
assistant cannot reference the same agent. Temperature, weights, and thresholds
must be finite numbers. Fields are strictly typed; booleans are not integers.

### Python tool references

The weather example exports a `tool.Tool` named `WEATHER`. A TOML file in
`examples/` references it like this:

```toml
[tools.weather]
file = "weather_tools.py"
object = "WEATHER"
```

Set `tools = ["weather"]` on the agent. For an installed module, use
`module = "your_package.tools"` instead of `file`. File paths resolve relative
to the TOML file. Imports do not change Python's module search path, so sibling
imports must already be available through your environment or package.

Validation checks referenced files exist without executing them. Building a
task imports its selected tools and checks they are `Tool` objects. Referenced
Python code executes during import; module names and exported objects are only
checked at build time.

### Load TOML from Python

```python
from synthaid import config
from synthaid import environment
from synthaid import export

definitions = config.load("examples/weather.toml")
print(definitions.task_names)
weather_task = definitions.build("weather")
environment.run(weather_task)
export.save(weather_task, "runs")
```

`config.load(path)` returns validated definitions without imports, credentials,
or model calls. `Config.path` is the absolute source path; `task_names` is a
tuple in declaration order. `Config.build(name)` resolves selected credentials
and tools and returns a fresh `Task`, without model calls.
`config.discover(path, recursive=False, exclude=None)` returns sorted absolute
TOML paths from a file or directory; `exclude` omits an output directory.

## CLI

| Command | Behavior |
| --- | --- |
| `synthaid validate PATH` | Validate a file or directory without imports or model calls |
| `synthaid run PATH` | Run all tasks and save each in a separate directory |
| `synthaid run FILE --task NAME` | Select one task from a single TOML file |
| `synthaid run DIRECTORY --recursive` | Include TOML files in subdirectories |
| `synthaid run PATH --root results` | Save under `results` instead of `runs` |

`validate` also accepts `--recursive` and `--root`. `python -m synthaid`
is equivalent to `synthaid`; use `uv run` before either command in a checkout.

Directory discovery finds immediate `*.toml` files by default, skips hidden
paths and the output root, and sorts file paths. Within each file, tasks run in
declaration order. Explicitly selecting a file includes it even in a hidden
path. Empty directories are errors. `--task` only works with a single file.

Before execution, the CLI validates every discovered file and builds all
selected tasks, resolving their credentials and Python tools. A preparation
error prevents the batch from starting. Execution is sequential. A failed task
is saved when possible and the remaining tasks continue. Interruption saves
the current task when possible and stops the batch. Only status and save paths
are printed; conversations are written to files.

| Exit code | Meaning |
| --- | --- |
| `0` | Validation succeeded, or every task completed and saved |
| `1` | At least one task failed during execution or saving |
| `2` | Invalid input or preparation failure |
| `130` | Interrupted |

The current CLI supports foreground validation and execution. Background jobs,
listing/viewing runs, cancellation, resume, and rerun commands are not
implemented yet.

## Results

`export.save(task, root)` creates a new `root/<time>-<id>/` directory and
returns its path. It also saves tasks that failed partway. The CLI calls it
automatically; Python callers call it explicitly.

| File | Contents |
| --- | --- |
| `exchange.txt` | Public conversation with role labels and inline tool calls |
| `exchange.json` | Assistant system instructions, public messages, and available tool schemas |
| `logs/assistant.json` | Assistant inputs, accepted/rejected drafts, feedback, and tool results |
| `logs/user.json` | Simulator log, including its private notes and tools; only when a simulator exists |
| `logs/assistant-evaluator.json` | Assistant evaluator's log when it is an `Agent`, such as `LLMJudge` |
| `logs/user-evaluator.json` | Simulator evaluator's log under the same condition |

For example, `exchange.txt` reads:

```text
[user] What's the weather in Lagos?
[assistant] calls get_weather({"city": "Lagos", "day": "today"})
[tool] {"city": "Lagos", "day": "today", "forecast": "31°C, humid, clear"}
[assistant] It is 31°C, humid, and clear in Lagos today.
```

JSON messages use the Chat Completions shape, retain available reasoning as
`reasoning_content`, and serialize structured content as JSON text. The text
transcript omits system instructions and reasoning. Rejected drafts, critiques,
and simulator tool activity stay out of the public exchange.

`export.to_record(task)` returns the training record as a dictionary with
`messages` and optional `tools`. `export.write_jsonl(tasks, path)` appends one
record per task to a UTF-8 JSON Lines file, creating it when needed:

```python
export.write_jsonl([trip], "training.jsonl")
```

Evaluation decisions and `EvalResult.metadata` are not saved as separate
records. LLM judge answers are available in evaluator logs; Python evaluators
have no automatic result log. Run directories do not currently contain a
manifest with configuration, execution status, or evaluation-budget outcomes.

## Errors

| Error | Cause |
| --- | --- |
| `config.ConfigError` | Invalid TOML, missing reference or credential, or unusable Python tool |
| `ValueError` | Invalid runtime configuration, or a judge's answers do not match its criteria |
| `exception.UnknownToolError` | The model requested an unavailable tool |
| `exception.ToolExecutionError` | A tool function raised; the original error is `__cause__` |
| `exception.ToolRoundsError` | A turn exceeded its tool-round limit |
| `openai.APIError` | Provider or transport failure |
| `pydantic.ValidationError` | Invalid structured output |
| `openai.LengthFinishReasonError` / `openai.ContentFilterFinishReasonError` | A structured reply was cut off or filtered |
| `json.JSONDecodeError` / `TypeError` | Invalid tool-argument JSON or a non-serializable tool result |

Import `exception` from `synthaid` for the tool errors. Unknown tool and tool
execution errors inherit from `ToolError` and expose the failing `call`.
Tool-round errors expose `max_tool_rounds`. Python callers receive exceptions;
the CLI reports them with the exit codes above. Agent logs survive failures.
If an assistant turn fails, public history retains previous turns and the
current user prompt; unfinished turn details remain in the agent's logs.

## Development

Follow the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
Use clear names, focused functions, and small public interfaces. Document
caller contracts and non-obvious decisions.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Live provider tests require `SYNTHAID_TEST_BASE_URL`, `SYNTHAID_TEST_API_KEY`,
and `SYNTHAID_TEST_MODEL`; otherwise they are skipped.
