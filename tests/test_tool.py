import json
from typing import Any

import pytest

from synthaid import exception
from synthaid import message
from synthaid import tool

_PARAMETERS = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}
_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)


def _get_weather(city: str) -> dict[str, Any]:
    return {"city": city, "temp_c": 31}


_WEATHER = tool.Tool(
    name="get_weather",
    description="Get the weather for a city",
    parameters=_PARAMETERS,
    function=_get_weather,
)


def test_to_chat_completions() -> None:
    assert _WEATHER.to_chat_completions() == {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": _PARAMETERS,
        },
    }


def test_call_returns_tool_result_message() -> None:
    result = _WEATHER(_CALL)

    assert result.role == "tool"
    assert result.tool_call_id == "call-1"
    assert json.loads(result.text) == {"city": "Lagos", "temp_c": 31}


def test_call_wraps_function_errors() -> None:
    def broken(city: str) -> str:
        raise RuntimeError("weather service down")

    failing = tool.Tool("get_weather", "Get the weather", _PARAMETERS, broken)

    with pytest.raises(exception.ToolExecutionError, match="call-1") as caught:
        failing(_CALL)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert caught.value.call == _CALL


def test_call_keeps_string_result() -> None:
    echo = tool.Tool("echo", "Echo the city", _PARAMETERS, lambda city: city)

    assert echo(_CALL) == message.Message(
        "tool", "Lagos", tool_call_id="call-1"
    )
