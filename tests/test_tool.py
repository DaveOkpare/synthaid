import json
from typing import Any

from synthaid.message import Message, ToolCall
from synthaid.tool import Tool

PARAMETERS = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}


def get_weather(city: str) -> dict[str, Any]:
    return {"city": city, "temp_c": 31}


WEATHER = Tool(
    name="get_weather",
    description="Get the weather for a city",
    parameters=PARAMETERS,
    function=get_weather,
)


def test_to_chat_completions() -> None:
    assert WEATHER.to_chat_completions() == {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": PARAMETERS,
        },
    }


def test_call_returns_tool_result_message() -> None:
    call = ToolCall(id="call-1", name="get_weather", arguments={"city": "Lagos"})

    result = WEATHER(call)

    assert result.role == "tool"
    assert result.tool_call_id == "call-1"
    assert json.loads(result.text) == {"city": "Lagos", "temp_c": 31}


def test_call_keeps_string_result() -> None:
    echo = Tool("echo", "Echo the text", PARAMETERS, function=lambda city: city)

    result = echo(ToolCall(id="call-1", name="echo", arguments={"city": "Lagos"}))

    assert result == Message("tool", "Lagos", tool_call_id="call-1")
