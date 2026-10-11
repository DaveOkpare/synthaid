# synthaid

A framework for generating verified traces from agent interactions.

## Usage

A user simulator talks to an assistant. A judge checks each of the
assistant's drafts against your criteria before it counts. When the run
ends, the conversation and every agent's logs are saved.

```python
from synthaid import agent
from synthaid import environment
from synthaid import evaluation
from synthaid import export
from synthaid import model
from synthaid import task

gpt = model.Model("openai/gpt-oss-120b", "https://api.doubleword.ai/v1")

judge = evaluation.LLMJudge(
    gpt,
    [
        evaluation.Criterion(content="Answers the question asked."),
        evaluation.Criterion(content="Makes up facts.", weight=-1),
    ],
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
export.save(trip, "runs")  # runs/<time>-<id>/exchange.json and logs/
```

`Model` works with any server that speaks Chat Completions. It reads the
API key from `OPENAI_API_KEY` when you don't pass `api_key`.

## TOML and the CLI

Validate a task file or a directory without credentials or model requests:

```sh
uv run synthaid validate examples/weather.toml
uv run synthaid validate examples/
```

Set `DOUBLEWORD_API_KEY` to run the weather example:

```sh
uv run synthaid run examples/weather.toml
uv run synthaid run examples/ --root runs/weather
```

The CLI runs every task in every immediate `*.toml` file in a directory,
in sorted file order and declaration order within each file. Add
`--recursive` to include subdirectories; hidden paths and the output root
are excluded. `--task weather` selects one task from a single file.
`python -m synthaid` is another way to invoke the CLI.

All definitions, selected credentials, and Python tools are checked before
model requests begin. Each task gets fresh agents and judges. The CLI prints
run status and save paths. Each run directory under `runs/<time>-<id>/`
contains `exchange.txt` for reading, `exchange.json` for training, and agent
logs, including partial runs when execution fails. The text transcript uses
`[user]`, `[assistant]`, and `[tool]` labels and shows tool calls inline.
Failed tasks do not stop the remaining batch. Exit codes are 0 for success,
1 for execution or saving failures,
2 for invalid input or preparation errors, and 130 for interruption.

For example, `exchange.txt` reads:

```text
[user] What's the weather in Lagos?
[assistant] calls get_weather({"city": "Lagos", "day": "today"})
[tool] {"city": "Lagos", "day": "today", "forecast": "31°C, humid, clear"}
[assistant] It is 31°C, humid, and clear in Lagos today.
```

Here is a minimal task file. It uses `OPENAI_API_KEY` by default:

```toml
schema_version = 1

[models.gpt]
model_name = "openai/gpt-oss-120b"
base_url = "https://api.doubleword.ai/v1"

[agents.assistant]
model = "gpt"
instructions = "You are a travel assistant."

[tasks.lagos]
assistant = "assistant"

[[tasks.lagos.steps]]
instruction = "What should I see in Lagos?"

[[tasks.lagos.steps]]
instruction = "When should I visit?"
```

Add a named agent and set `user` on a task for a user simulator. Each
`[[tasks.NAME.steps]]` table adds an ordered step. `max_turns` defaults to
1; without a simulator, each step always produces one exchange.

The full `examples/weather.toml` also defines a judge and a Python tool:

```toml
[tools.weather]
file = "weather_tools.py"
object = "WEATHER"

[evaluators.weather]
kind = "llm"
model = "gpt"

[[evaluators.weather.criteria]]
content = "Uses tool results for weather facts."
weight = 1.0

[[evaluators.weather.criteria]]
content = "Invents weather facts."
weight = -1.0
```

An agent uses `tools = ["weather"]` and `evaluator = "weather"` to reference
these definitions. A judge accepts optional `instructions` and `threshold`.
Each criterion defaults to weight 1.0. Agent limits default to
`max_iterations = 3` and `max_tool_rounds = 10`; the last draft is still
accepted when its reflection budget runs out.

Models accept `api_key_env` and `temperature` (default 0.7). Tool references
use either a config-relative `file` or an importable `module`, plus the
exported `object`, which must be a `synthaid.tool.Tool`. Running a task imports
its referenced Python code; validation only checks the file's existence.
File imports do not change Python's module search path. Unknown fields and
references are rejected with field-path errors. TOML currently supports text
agents, Python tools, and built-in LLM judges.

Python callers can use the same loader:

```python
from synthaid import config

definitions = config.load("examples/weather.toml")
weather_task = definitions.build("weather")
environment.run(weather_task)
export.save(weather_task, "runs")
```

The weather scenario lives in `examples/weather.toml`; `examples/weather_tools.py`
contains its Python tool implementation.

## Development

Follow the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html).
Use clear names, small focused functions, and straightforward control flow.
Keep public interfaces small and hide validation and state management inside
their owning modules. Document caller contracts and non-obvious decisions.

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
```
