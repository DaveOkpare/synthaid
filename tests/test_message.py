import json

from openai.types import chat
import pydantic
import pytest

from synthaid import message


class Event(pydantic.BaseModel):
    name: str
    date: str


def _function_call(arguments: str) -> dict[str, object]:
    return {
        "id": "call-1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": arguments},
    }


def test_text_dumps_structured_content_to_json() -> None:
    event = message.Message("assistant", Event(name="fair", date="Friday"))

    assert json.loads(event.text) == {"name": "fair", "date": "Friday"}


def test_text_of_missing_content_is_empty() -> None:
    assert message.Message("assistant", None).text == ""


def test_to_chat_completions_drops_reasoning() -> None:
    reply = message.Message("assistant", "hi", reasoning="thinking")

    assert reply.to_chat_completions() == {"role": "assistant", "content": "hi"}


def test_to_chat_completions_dumps_structured_content() -> None:
    event = message.Message("assistant", Event(name="fair", date="Friday"))

    assert event.to_chat_completions() == {
        "role": "assistant",
        "content": '{"name":"fair","date":"Friday"}',
    }


def test_to_chat_completions_writes_tool_call() -> None:
    call = message.ToolCall(
        id="call-1", name="get_weather", arguments={"city": "Lagos"}
    )
    reply = message.Message("assistant", None, tool_calls=(call,))

    assert reply.to_chat_completions() == {
        "role": "assistant",
        "content": None,
        "tool_calls": [_function_call('{"city": "Lagos"}')],
    }


def test_to_chat_completions_writes_tool_result() -> None:
    result = message.Message("tool", '{"temp_c": 31}', tool_call_id="call-1")

    assert result.to_chat_completions() == {
        "role": "tool",
        "content": '{"temp_c": 31}',
        "tool_call_id": "call-1",
    }


def test_from_chat_completions_reads_text_and_reasoning() -> None:
    reply = chat.ChatCompletionMessage.model_validate(
        {"role": "assistant", "content": "hi", "reasoning_content": "thinking"}
    )

    assert message.Message.from_chat_completions(reply) == message.Message(
        "assistant", "hi", reasoning="thinking"
    )


def test_from_chat_completions_prefers_parsed() -> None:
    event = Event(name="fair", date="Friday")
    reply = chat.ParsedChatCompletionMessage[Event](
        role="assistant", content=event.model_dump_json(), parsed=event
    )

    assert message.Message.from_chat_completions(reply).content == event


def test_from_chat_completions_decodes_tool_arguments() -> None:
    reply = chat.ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_function_call('{"city":"Lagos"}')],
        }
    )

    assert message.Message.from_chat_completions(reply).tool_calls == (
        message.ToolCall(
            id="call-1", name="get_weather", arguments={"city": "Lagos"}
        ),
    )


def test_from_chat_completions_rejects_bad_tool_arguments() -> None:
    reply = chat.ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [_function_call("{city")],
        }
    )

    with pytest.raises(json.JSONDecodeError):
        message.Message.from_chat_completions(reply)
