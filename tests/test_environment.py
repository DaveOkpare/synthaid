"""Environment tests.

The live test calls a real server and is skipped unless
SYNTHAID_TEST_BASE_URL, SYNTHAID_TEST_API_KEY and SYNTHAID_TEST_MODEL
are set.
"""

import os

import pydantic
import pytest

from synthaid import agent
from synthaid import environment
from synthaid import evaluation
from synthaid import exception
from synthaid import message
from synthaid import model
from synthaid import task
from synthaid import tool
from tests import fakes

_LIVE_ENV = (
    "SYNTHAID_TEST_BASE_URL",
    "SYNTHAID_TEST_API_KEY",
    "SYNTHAID_TEST_MODEL",
)
live = pytest.mark.skipif(
    not all(os.environ.get(name) for name in _LIVE_ENV),
    reason=f"set {', '.join(_LIVE_ENV)} to run live tests",
)

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


def _says(text: str) -> message.Message:
    return message.Message("assistant", text)


def _calls_weather() -> message.Message:
    return message.Message("assistant", None, tool_calls=(_CALL,))


def _weather_result() -> message.Message:
    return message.Message("tool", "31°C", tool_call_id="call-1")


def _run(the_task: task.Task) -> list[message.Message]:
    environment.run(the_task)
    return the_task.chat_history


def test_single_agent_adds_instruction_and_reply() -> None:
    assistant = fakes.scripted(_says("It is sunny."))

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
    assistant = fakes.scripted(_says("It is sunny."), _says("Rain later."))

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
    user = fakes.scripted(_says("u1"), _says("u2"), _says("u3"))
    assistant = fakes.scripted(_says("a1"), _says("a2"), _says("a3"))

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
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(_says("a1"), _says("a2"))

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
    user = fakes.scripted(_says("u1"))
    assistant = fakes.scripted(_says("a1"))

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


def test_simulator_sees_swapped_roles_then_a_separate_note() -> None:
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(_says("a1"), _says("a2"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    _, own, reply, note = user.seen(1)
    assert own == _says("u1")
    assert reply == message.Message("user", "a1")
    assert note.role == "user"
    assert _INSTRUCTION in note.text
    assert "turn 2 of 2" in note.text


def test_simulator_view_only_grows_across_turns_and_steps() -> None:
    user = fakes.scripted(_says("u1"), _says("u2"), _says("u3"))
    assistant = fakes.scripted(_says("a1"), _says("a2"), _says("a3"))
    simulator = agent.Agent(user, "Act as a customer.")

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [
                task.Step(_INSTRUCTION, max_turns=2),
                task.Step("Ask about tomorrow."),
            ],
            user=simulator,
        )
    )

    # Each request is the last one, then the simulator's reply, the
    # assistant's reply, and the next note.
    for index in (1, 2):
        before = user.seen(index - 1)
        after = user.seen(index)
        assert after[: len(before)] == before
        added = after[len(before) :]
        assert added[:2] == [
            _says(f"u{index}"),
            message.Message("user", f"a{index}"),
        ]
        assert len(added) == 3
    assert [item.role for item in simulator.logs].count("system") == 1


def test_note_asks_to_close_on_last_turn_only() -> None:
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(_says("a1"), _says("a2"))

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
    user = fakes.scripted(_says("u1"))
    assistant = fakes.scripted(_says("a1"))

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
    user = fakes.scripted(_says("u1"))
    assistant = fakes.scripted(_says("a1"))
    starting = [message.Message("user", "Hi."), _says("Hello.")]

    history = _run(
        task.Task(
            agent.Agent(assistant, "Be helpful."),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(user, "Act as a customer."),
            chat_history=list(starting),
        )
    )

    own, reply, note = user.seen(0)
    assert own == _says("Hi.")
    assert reply == message.Message("user", "Hello.")
    assert _INSTRUCTION in note.text
    assert assistant.seen(0) == [*starting, message.Message("user", "u1")]
    assert history[:2] == starting


def test_assistant_never_sees_instruction_or_note() -> None:
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(_says("a1"), _says("a2"))

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
    user = fakes.scripted(_says("u1"))
    assistant = fakes.scripted(_calls_weather(), _says("It is 31°C."))

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
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(
        _calls_weather(), _says("It is 31°C."), _says("a2")
    )

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful.", tools=[_WEATHER]),
            [task.Step(_INSTRUCTION, max_turns=2)],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    _, own, reply, _ = user.seen(1)
    assert own == _says("u1")
    assert reply == message.Message("user", "It is 31°C.")


def test_simulator_tool_messages_stay_out_of_history() -> None:
    user = fakes.scripted(_calls_weather(), _says("Is it hot?"))
    assistant = fakes.scripted(_says("Yes."))
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
    user = fakes.scripted(
        message.Message("assistant", "Hi.", reasoning="Start small.")
    )
    assistant = fakes.scripted(_says("Hello."))

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
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(
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
    assert user.seen(1)[-2] == message.Message("user", '{"city":"Lagos"}')


def test_history_keeps_finished_turns_when_assistant_fails() -> None:
    user = fakes.scripted(_says("u1"), _says("u2"))
    assistant = fakes.scripted(_says("a1"), _calls_weather())
    the_task = task.Task(
        agent.Agent(assistant, "Be helpful."),
        [task.Step(_INSTRUCTION, max_turns=2)],
        user=agent.Agent(user, "Act as a customer."),
    )

    with pytest.raises(exception.UnknownToolError):
        environment.run(the_task)

    assert the_task.chat_history == [
        message.Message("user", "u1"),
        _says("a1"),
        message.Message("user", "u2"),
    ]


def test_assistant_evaluator_sees_whole_conversation() -> None:
    drafts: list[agent.Draft] = []

    def evaluate(draft: agent.Draft) -> evaluation.EvalResult:
        drafts.append(draft)
        return evaluation.EvalResult("", passed=True)

    user = fakes.scripted(_says("u1"), _says("u2"), _says("u3"))
    assistant = fakes.scripted(_says("a1"), _says("a2"), _says("a3"))

    _run(
        task.Task(
            agent.Agent(assistant, "Be helpful.", evaluator=evaluate),
            [
                task.Step(_INSTRUCTION),
                task.Step("Ask about tomorrow.", max_turns=2),
            ],
            user=agent.Agent(user, "Act as a customer."),
        )
    )

    # The judge of the second step still sees the first step.
    assert drafts[1].context == [
        message.Message("user", "u1"),
        _says("a1"),
        message.Message("user", "u2"),
    ]
    assert drafts[2].context == [
        message.Message("user", "u1"),
        _says("a1"),
        message.Message("user", "u2"),
        _says("a2"),
        message.Message("user", "u3"),
    ]


def test_judge_never_sees_the_step_instruction() -> None:
    criterion = evaluation.Criterion(content="Answers the question.")
    verdict = evaluation.Verdict(
        answers=[
            evaluation.Answer(content=criterion.content, met=evaluation.Met.YES)
        ],
        feedback="Fine.",
    )
    judge_model = fakes.scripted(message.Message("assistant", verdict))

    _run(
        task.Task(
            agent.Agent(
                fakes.scripted(_says("a1")),
                "Be helpful.",
                evaluator=evaluation.LLMJudge(judge_model, [criterion]),
            ),
            [task.Step(_INSTRUCTION)],
            user=agent.Agent(fakes.scripted(_says("u1")), "Act as a user."),
        )
    )

    prompt = judge_model.seen(0)[0].text
    assert _INSTRUCTION not in prompt
    assert "Step instruction" not in prompt


_REPEATS = evaluation.Criterion(
    content=(
        "The draft asks again for information the assistant already gave "
        "earlier in the conversation."
    ),
    weight=-1.0,
)


@live
@pytest.mark.parametrize("trial", range(10))
def test_live_simulator_does_not_repeat_an_answered_question(
    trial: int,
) -> None:
    live_model = model.Model(
        model_name=os.environ["SYNTHAID_TEST_MODEL"],
        base_url=os.environ["SYNTHAID_TEST_BASE_URL"],
        api_key=os.environ["SYNTHAID_TEST_API_KEY"],
    )
    assistant = fakes.scripted(
        _says("Today in Lagos it is 31°C, humid, with clear skies."),
        _says("Happy to help with anything else about your trip."),
    )
    the_task = task.Task(
        agent.Agent(assistant, "Be helpful."),
        [task.Step("Ask what the weather is like in Lagos today.", 2)],
        user=agent.Agent(
            live_model,
            "You are a traveller planning a trip to Lagos. Write short, "
            "casual messages, one question at a time.",
        ),
    )

    history = _run(the_task)

    second = history[2]
    result = evaluation.LLMJudge(live_model, [_REPEATS])(
        agent.Draft(second, context=history[:2])
    )
    assert result.passed, f"{second.text!r}: {result.feedback}"
