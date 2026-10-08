"""Model tests.

The live tests call a real server and are skipped unless
SYNTHAID_TEST_BASE_URL, SYNTHAID_TEST_API_KEY and SYNTHAID_TEST_MODEL
are set.
"""

import os

import pytest
from pydantic import BaseModel

from synthaid.message import Message
from synthaid.model import Model
from synthaid.tool import Tool

LIVE_ENV = ("SYNTHAID_TEST_BASE_URL", "SYNTHAID_TEST_API_KEY", "SYNTHAID_TEST_MODEL")
live = pytest.mark.skipif(
    not all(os.environ.get(name) for name in LIVE_ENV),
    reason=f"set {', '.join(LIVE_ENV)} to run live tests",
)


class CalendarEvent(BaseModel):
    name: str
    date: str
    participants: list[str]


WEATHER = Tool(
    name="get_weather",
    description="Get the weather for a city",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
    function=lambda city: {"city": city, "temp_c": 31, "sky": "sunny"},
)


def live_model() -> Model:
    return Model(
        model_name=os.environ["SYNTHAID_TEST_MODEL"],
        base_url=os.environ["SYNTHAID_TEST_BASE_URL"],
        api_key=os.environ["SYNTHAID_TEST_API_KEY"],
    )


def test_generate_rejects_tools_with_structured_output() -> None:
    model = Model(model_name="any", base_url="http://unused", api_key="unused")

    with pytest.raises(ValueError):
        model.generate(
            [Message("user", "hi")], tools=[WEATHER], output_type=CalendarEvent
        )


@live
def test_live_text_reply() -> None:
    reply = live_model().generate([Message("user", "Say hello in one word.")])

    assert reply.role == "assistant"
    assert isinstance(reply.content, str) and reply.content
    assert reply.reasoning


@live
def test_live_structured_reply() -> None:
    reply = live_model().generate(
        [
            Message("system", "Extract the event information."),
            Message("user", "Alice and Bob are going to a science fair on Friday."),
        ],
        output_type=CalendarEvent,
    )

    assert isinstance(reply.content, CalendarEvent)
    assert set(reply.content.participants) == {"Alice", "Bob"}


@live
def test_live_tool_round_trip() -> None:
    model = live_model()
    messages = [Message("user", "What's the weather in Lagos?")]

    call_reply = model.generate(messages, tools=[WEATHER])
    (call,) = call_reply.tool_calls
    messages += [call_reply, WEATHER(call)]
    answer = model.generate(messages, tools=[WEATHER])

    assert call.arguments == {"city": "Lagos"}
    assert isinstance(answer.content, str) and "31" in answer.content
