import json

import pytest
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.parsed_chat_completion import ParsedChatCompletionMessage
from pydantic import BaseModel

from synthaid.message import Message, ToolCall


class Event(BaseModel):
    name: str
    date: str


def test_text_dumps_structured_content_to_json() -> None:
    message = Message("assistant", Event(name="fair", date="Friday"))

    assert json.loads(message.text) == {"name": "fair", "date": "Friday"}


def test_text_of_missing_content_is_empty() -> None:
    assert Message("assistant", None).text == ""


def test_to_chat_completions_drops_reasoning() -> None:
    message = Message("assistant", "hi", reasoning="thinking")

    assert message.to_chat_completions() == {"role": "assistant", "content": "hi"}


def test_to_chat_completions_dumps_structured_content() -> None:
    message = Message("assistant", Event(name="fair", date="Friday"))

    assert message.to_chat_completions() == {
        "role": "assistant",
        "content": '{"name":"fair","date":"Friday"}',
    }


def test_to_chat_completions_writes_tool_call() -> None:
    call = ToolCall(id="call-1", name="get_weather", arguments={"city": "Lagos"})
    message = Message("assistant", None, tool_calls=(call,))

    assert message.to_chat_completions() == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "Lagos"}'},
            }
        ],
    }


def test_to_chat_completions_writes_tool_result() -> None:
    message = Message("tool", '{"temp_c": 31}', tool_call_id="call-1")

    assert message.to_chat_completions() == {
        "role": "tool",
        "content": '{"temp_c": 31}',
        "tool_call_id": "call-1",
    }


def test_from_chat_completions_reads_text_and_reasoning() -> None:
    reply = ChatCompletionMessage.model_validate(
        {"role": "assistant", "content": "hi", "reasoning_content": "thinking"}
    )

    assert Message.from_chat_completions(reply) == Message(
        "assistant", "hi", reasoning="thinking"
    )


def test_from_chat_completions_prefers_parsed() -> None:
    event = Event(name="fair", date="Friday")
    reply = ParsedChatCompletionMessage[Event](
        role="assistant", content=event.model_dump_json(), parsed=event
    )

    assert Message.from_chat_completions(reply).content == event


def test_from_chat_completions_decodes_tool_arguments() -> None:
    reply = ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"city":"Lagos"}',
                    },
                }
            ],
        }
    )

    message = Message.from_chat_completions(reply)

    assert message.tool_calls == (
        ToolCall(id="call-1", name="get_weather", arguments={"city": "Lagos"}),
    )


def test_from_chat_completions_rejects_bad_tool_arguments() -> None:
    reply = ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": "{city"},
                }
            ],
        }
    )

    with pytest.raises(json.JSONDecodeError):
        Message.from_chat_completions(reply)
