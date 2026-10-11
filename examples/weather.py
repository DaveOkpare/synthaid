"""Runs a two-agent weather conversation on Doubleword's gpt-oss-120b.

A user simulator plays a traveller. The assistant answers with a
`get_weather` tool, and an LLMJudge checks every draft against the step's
conversation before it counts. Each run is saved in its own directory
under runs/weather/: the exchange, and the logs of the assistant, the
traveller and the judge.

Set DOUBLEWORD_API_KEY, then run:

    uv run python examples/weather.py
"""

from collections.abc import Sequence
import dataclasses
import json
import os
import pathlib
from typing import Any

import pydantic

from synthaid import agent
from synthaid import environment
from synthaid import evaluation
from synthaid import export
from synthaid import message
from synthaid import model
from synthaid import task
from synthaid import tool

_BASE_URL = "https://api.doubleword.ai/v1"
_MODEL_NAME = "openai/gpt-oss-120b"
_RUNS = pathlib.Path("runs/weather")

_FORECASTS = {
    "lagos": {"today": "31°C, humid, clear", "tomorrow": "28°C, heavy rain"},
    "abuja": {"today": "33°C, dry, sunny", "tomorrow": "32°C, sunny"},
}


def get_weather(city: str, day: str = "today") -> dict[str, Any]:
    """Returns made-up weather for `city` on `day` ("today" or "tomorrow")."""
    forecast = _FORECASTS.get(city.lower())
    if forecast is None:
        return {"city": city, "error": "No forecast for this city."}
    return {"city": city, "day": day, "forecast": forecast[day]}


_WEATHER = tool.Tool(
    name="get_weather",
    description="Gets the weather forecast for a city, today or tomorrow.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "The city name."},
            "day": {"type": "string", "enum": ["today", "tomorrow"]},
        },
        "required": ["city"],
    },
    function=get_weather,
)

_CRITERIA = [
    evaluation.Criterion(
        content=(
            "The draft calls get_weather, or its weather facts match a "
            "get_weather result in the conversation."
        ),
    ),
    evaluation.Criterion(
        content="States weather facts that no get_weather result in the "
        "conversation provided.",
        weight=-1.0,
    ),
]


@dataclasses.dataclass(frozen=True)
class _CountingModel(model.Model):
    """A Model that counts the requests it sends."""

    sent: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"requests": 0}
    )

    def generate(
        self,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        """Counts the request, then sends it."""
        self.sent["requests"] += 1
        return super().generate(messages, tools=tools, output_type=output_type)


def _model() -> _CountingModel:
    """Returns a new counting Model for gpt-oss-120b on Doubleword."""
    return _CountingModel(
        _MODEL_NAME, _BASE_URL, api_key=os.environ["DOUBLEWORD_API_KEY"]
    )


def _show(item: message.Message) -> str:
    """Returns one history message as a line for the terminal."""
    if item.tool_calls:
        calls = ", ".join(
            f"{call.name}({json.dumps(call.arguments)})"
            for call in item.tool_calls
        )
        return f"[{item.role}] calls {calls}"
    return f"[{item.role}] {item.text}"


def main() -> None:
    """Runs the conversation, saves it, and prints what happened."""
    models = {"traveller": _model(), "assistant": _model(), "judge": _model()}
    assistant = agent.Agent(
        models["assistant"],
        "You are a travel assistant. Use get_weather for every weather "
        "fact. Answer in two or three sentences.",
        tools=[_WEATHER],
        evaluator=evaluation.LLMJudge(models["judge"], _CRITERIA),
    )
    traveller = agent.Agent(
        models["traveller"],
        "You are a traveller planning a trip to Lagos. Write short, "
        "casual messages, one question at a time.",
    )
    weather_task = task.Task(
        assistant,
        [
            task.Step("Ask what the weather is like in Lagos today.", 2),
            task.Step("Ask whether to pack an umbrella for tomorrow."),
        ],
        user=traveller,
    )

    try:
        environment.Environment().run(weather_task)
    finally:
        directory = export.save(weather_task, _RUNS)
        print(f"saved to {directory}")

    for item in weather_task.chat_history:
        print(_show(item))
    accepted = [
        item for item in weather_task.chat_history if item.role == "assistant"
    ]
    tool_runs = [
        item for item in weather_task.chat_history if item.role == "tool"
    ]
    print()
    for name, counting in models.items():
        print(f"{name} requests: {counting.sent['requests']}")
    total = sum(counting.sent["requests"] for counting in models.values())
    print(f"total requests: {total}")
    drafts = models["assistant"].sent["requests"]
    print(f"assistant drafts: {drafts}, rejected: {drafts - len(accepted)}")
    print(f"tool runs: {len(tool_runs)}")


if __name__ == "__main__":
    main()
