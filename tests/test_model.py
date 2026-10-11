"""Model tests.

The live tests call a real server and are skipped unless
SYNTHAID_TEST_BASE_URL, SYNTHAID_TEST_API_KEY and SYNTHAID_TEST_MODEL
are set.
"""

import os

import pydantic
import pytest

from synthaid import message
from synthaid import model
from synthaid import tool

_LIVE_ENV = (
    "SYNTHAID_TEST_BASE_URL",
    "SYNTHAID_TEST_API_KEY",
    "SYNTHAID_TEST_MODEL",
)
live = pytest.mark.skipif(
    not all(os.environ.get(name) for name in _LIVE_ENV),
    reason=f"set {', '.join(_LIVE_ENV)} to run live tests",
)


class CalendarEvent(pydantic.BaseModel):
    name: str
    date: str
    participants: list[str]


_WEATHER = tool.Tool(
    name="get_weather",
    description="Get the weather for a city",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
    function=lambda city: {"city": city, "temp_c": 31, "sky": "sunny"},
)


def _live_model() -> model.Model:
    return model.Model(
        model_name=os.environ["SYNTHAID_TEST_MODEL"],
        base_url=os.environ["SYNTHAID_TEST_BASE_URL"],
        api_key=os.environ["SYNTHAID_TEST_API_KEY"],
    )


def test_generate_rejects_tools_with_structured_output() -> None:
    offline = model.Model(
        model_name="any", base_url="http://unused", api_key="unused"
    )

    with pytest.raises(ValueError):
        offline.generate(
            [message.Message("user", "hi")],
            tools=[_WEATHER],
            output_type=CalendarEvent,
        )


@live
def test_live_text_reply() -> None:
    reply = _live_model().generate(
        [message.Message("user", "Say hello in one word.")]
    )

    assert reply.role == "assistant"
    assert isinstance(reply.content, str) and reply.content
    assert reply.reasoning


@live
def test_live_structured_reply() -> None:
    reply = _live_model().generate(
        [
            message.Message("system", "Extract the event information."),
            message.Message(
                "user", "Alice and Bob are going to a science fair on Friday."
            ),
        ],
        output_type=CalendarEvent,
    )

    assert isinstance(reply.content, CalendarEvent)
    assert set(reply.content.participants) == {"Alice", "Bob"}


@live
def test_live_tool_round_trip() -> None:
    live_model = _live_model()
    conversation = [message.Message("user", "What's the weather in Lagos?")]

    call_reply = live_model.generate(conversation, tools=[_WEATHER])
    (call,) = call_reply.tool_calls
    conversation += [call_reply, _WEATHER(call)]
    answer = live_model.generate(conversation, tools=[_WEATHER])

    assert call.arguments == {"city": "Lagos"}
    assert isinstance(answer.content, str) and "31" in answer.content
