from collections.abc import Sequence
import dataclasses

import pydantic
import pytest

from synthaid import agent
from synthaid import environment
from synthaid import exception
from synthaid import message
from synthaid import model
from synthaid import task
from synthaid import tool

_INSTRUCTION = "Ask about the weather in Lagos."
_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)
_WEATHER = tool.Tool(
    name="get_weather",
    description="Gets the weather for a city.",
    parameters={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
    function=lambda city: "31°C",
)


class _Forecast(pydantic.BaseModel):
    city: str


@dataclasses.dataclass(frozen=True)
class _ScriptedModel(model.Model):
    """Returns `replies` in order and records every request's messages."""

    replies: list[message.Message] = dataclasses.field(default_factory=list)
    requests: list[list[message.Message]] = dataclasses.field(
        default_factory=list
    )

    def generate(
        self,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        self.requests.append(list(messages))
        return self.replies.pop(0)

    def seen(self, index: int) -> list[message.Message]:
        """The messages of request `index`, without the system message."""
        return self.requests[index][1:]


def _scripted(*replies: message.Message) -> _ScriptedModel:
    return _ScriptedModel("test-model", "http://localhost", replies=[*replies])


def _says(text: str) -> message.Message:
    return message.Message("assistant", text)


def _calls_weather() -> message.Message:
    return message.Message("assistant", None, tool_calls=(_CALL,))


def _weather_result() -> message.Message:
    return message.Message("tool", "31°C", tool_call_id="call-1")


def _run(the_task: task.Task) -> list[message.Message]:
    environment.Environment().run(the_task)
    return the_task.chat_history


def test_single_agent_adds_instruction_and_reply() -> None:
    assistant = _scripted(_says("It is sunny."))

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION, max_turns=3)],
        )
    )

    assert history == [
        message.Message("user", _INSTRUCTION),
        _says("It is sunny."),
    ]
    assert len(assistant.requests) == 1


def test_single_agent_runs_later_steps_on_history() -> None:
    assistant = _scripted(_says("It is sunny."), _says("Rain later."))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION), task.Step("Ask about tomorrow.")],
        )
    )

    assert assistant.seen(1) == [
        message.Message("user", _INSTRUCTION),
        _says("It is sunny."),
        message.Message("user", "Ask about tomorrow."),
    ]


def test_simulator_speaks_first_for_max_turns() -> None:
    user = _scripted(_says("u1"), _says("u2"), _says("u3"))
    assistant = _scripted(_says("a1"), _says("a2"), _says("a3"))

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION, max_turns=3)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert [(item.role, item.content) for item in history] == [
        ("user", "u1"),
        ("assistant", "a1"),
        ("user", "u2"),
        ("assistant", "a2"),
        ("user", "u3"),
        ("assistant", "a3"),
    ]


def test_simulator_opens_every_step() -> None:
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(_says("a1"), _says("a2"))

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION), task.Step("Ask about tomorrow.")],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert [item.role for item in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert "Ask about tomorrow." in user.seen(1)[-1].text


def test_simulator_sees_note_alone_when_history_is_empty() -> None:
    user = _scripted(_says("u1"))
    assistant = _scripted(_says("a1"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    (note,) = user.seen(0)
    assert note.role == "user"
    assert _INSTRUCTION in note.text
    assert "turn 1 of 1" in note.text


def test_simulator_sees_swapped_roles_with_note_merged() -> None:
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(_says("a1"), _says("a2"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    own, reply = user.seen(1)
    assert own == _says("u1")
    assert reply.role == "user"
    assert reply.text.startswith("a1\n\n")
    assert _INSTRUCTION in reply.text
    assert "turn 2 of 2" in reply.text


def test_note_asks_to_close_on_last_turn_only() -> None:
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(_says("a1"), _says("a2"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert "last turn" not in user.seen(0)[-1].text
    assert "last turn" in user.seen(1)[-1].text


def test_note_is_own_message_when_history_ends_with_user() -> None:
    user = _scripted(_says("u1"))
    assistant = _scripted(_says("a1"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(user, "Act as a customer."),
            chat_history=[message.Message("user", "Hi.")],
        )
    )

    swapped, note = user.seen(0)
    assert swapped == _says("Hi.")
    assert note.role == "user"
    assert _INSTRUCTION in note.text


def test_simulator_builds_on_starting_history() -> None:
    user = _scripted(_says("u1"))
    assistant = _scripted(_says("a1"))
    starting = [message.Message("user", "Hi."), _says("Hello.")]

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(user, "Act as a customer."),
            chat_history=list(starting),
        )
    )

    own, reply = user.seen(0)
    assert own == _says("Hi.")
    assert reply.text.startswith("Hello.\n\n")
    assert assistant.seen(0) == [*starting, message.Message("user", "u1")]
    assert history[:2] == starting


def test_assistant_never_sees_instruction_or_note() -> None:
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(_says("a1"), _says("a2"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert assistant.seen(1) == [
        message.Message("user", "u1"),
        _says("a1"),
        message.Message("user", "u2"),
    ]


def test_history_keeps_assistant_tool_messages() -> None:
    user = _scripted(_says("u1"))
    assistant = _scripted(_calls_weather(), _says("It is 31°C."))

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful.", tools=[_WEATHER]),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert history == [
        message.Message("user", "u1"),
        _calls_weather(),
        _weather_result(),
        _says("It is 31°C."),
    ]


def test_simulator_does_not_see_assistant_tool_messages() -> None:
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(_calls_weather(), _says("It is 31°C."), _says("a2"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful.", tools=[_WEATHER]),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    own, reply = user.seen(1)
    assert own == _says("u1")
    assert reply.text.startswith("It is 31°C.\n\n")
    assert not reply.tool_calls


def test_simulator_tool_messages_stay_out_of_history() -> None:
    user = _scripted(_calls_weather(), _says("Is it hot?"))
    assistant = _scripted(_says("Yes."))
    simulator = agent.Agent(user, "Act as a customer.", tools=[_WEATHER])

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION)],
            user=simulator,
        )
    )

    assert history == [message.Message("user", "Is it hot?"), _says("Yes.")]
    assert _weather_result() in simulator.logs


def test_simulator_reply_keeps_reasoning_as_user_message() -> None:
    user = _scripted(
        message.Message("assistant", "Hi.", reasoning="Start small.")
    )
    assistant = _scripted(_says("Hello."))

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert history[0] == message.Message(
        "user", "Hi.", reasoning="Start small."
    )


def test_structured_reply_reaches_simulator_as_json() -> None:
    forecast = _Forecast(city="Lagos")
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(
        message.Message("assistant", forecast),
        message.Message("assistant", _Forecast(city="Abuja")),
    )

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful.", output_type=_Forecast),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    assert history[1].content == forecast
    assert user.seen(1)[-1].text.startswith('{"city":"Lagos"}\n\n')


def test_history_keeps_finished_turns_when_assistant_fails() -> None:
    user = _scripted(_says("u1"), _says("u2"))
    assistant = _scripted(_says("a1"), _calls_weather())
    the_task = task.Task(
        agent.Agent(assistant, "Be helpful."),
        [task.Step(_INSTRUCTION, max_turns=2)],
        user=agent.Agent(user, "Act as a customer."),
    )

    with pytest.raises(exception.UnknownToolError):
        environment.Environment().run(the_task)

    assert the_task.chat_history == [
        message.Message("user", "u1"),
        _says("a1"),
        message.Message("user", "u2"),
    ]
