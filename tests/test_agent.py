import dataclasses

import pydantic
import pytest

from synthaid import agent
from synthaid import evaluation
from synthaid import exception
from synthaid import message
from synthaid import tool
from tests import fakes

_SYSTEM = message.Message("system", "Be helpful.")
_QUESTION = message.Message("user", "What is the weather in Lagos?")
_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)


class _Forecast(pydantic.BaseModel):
    city: str


def _passed() -> evaluation.EvalResult:
    return evaluation.EvalResult("", passed=True)


def _failed(feedback: str) -> evaluation.EvalResult:
    return evaluation.EvalResult(feedback, passed=False)


@dataclasses.dataclass
class _ScriptedEvaluator:
    """Returns `results` in order and records every draft it sees."""

    results: list[evaluation.EvalResult]
    drafts: list[agent.Draft] = dataclasses.field(default_factory=list)

    def __call__(self, draft: agent.Draft) -> evaluation.EvalResult:
        self.drafts.append(draft)
        return self.results.pop(0)

    @property
    def messages(self) -> list[message.Message]:
        return [item.message for item in self.drafts]


def _assistant(content: str) -> message.Message:
    return message.Message("assistant", content)


def _weather_tool(name: str = "get_weather") -> tool.Tool:
    return tool.Tool(
        name=name,
        description="Get the weather for a city",
        parameters={"type": "object"},
        function=lambda city: f"Sunny in {city}",
    )


_TOOL_DRAFT = message.Message("assistant", None, tool_calls=(_CALL,))
_TOOL_RESULT = message.Message("tool", "Sunny in Lagos", tool_call_id="call-1")


def test_rejects_tools_with_structured_output() -> None:
    with pytest.raises(ValueError, match="structured output"):
        agent.Agent(
            fakes.scripted(), "Be helpful.", _Forecast, tools=[_weather_tool()]
        )


def test_rejects_duplicate_tool_names() -> None:
    with pytest.raises(ValueError, match="get_weather"):
        agent.Agent(
            fakes.scripted(),
            "Be helpful.",
            tools=[_weather_tool(), _weather_tool()],
        )


def test_rejects_max_iterations_below_one() -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        agent.Agent(fakes.scripted(), "Be helpful.", max_iterations=0)


def test_rejects_max_tool_rounds_below_one() -> None:
    with pytest.raises(ValueError, match="max_tool_rounds"):
        agent.Agent(fakes.scripted(), "Be helpful.", max_tool_rounds=0)


def test_run_allows_exactly_max_tool_rounds() -> None:
    fake = fakes.scripted(_TOOL_DRAFT, _TOOL_DRAFT, _assistant("Sunny."))
    helper = agent.Agent(
        fake, "Be helpful.", tools=[_weather_tool()], max_tool_rounds=2
    )

    turn = helper.run([_QUESTION])

    assert turn[-1] == _assistant("Sunny.")
    assert turn.count(_TOOL_RESULT) == 2


def test_run_raises_when_tool_rounds_run_out() -> None:
    fake = fakes.scripted(_TOOL_DRAFT, _TOOL_DRAFT)
    helper = agent.Agent(
        fake, "Be helpful.", tools=[_weather_tool()], max_tool_rounds=1
    )

    with pytest.raises(exception.ToolRoundsError, match="1"):
        helper.run([_QUESTION])

    # The first round ran, and the draft over the limit is in the logs.
    assert helper.logs[-2:] == [_TOOL_RESULT, _TOOL_DRAFT]


def test_tool_rounds_count_per_turn() -> None:
    fake = fakes.scripted(
        _TOOL_DRAFT, _assistant("Sunny."), _TOOL_DRAFT, _assistant("Still.")
    )
    helper = agent.Agent(
        fake, "Be helpful.", tools=[_weather_tool()], max_tool_rounds=1
    )

    helper.run([_QUESTION])
    turn = helper.run([_QUESTION])

    assert turn[-1] == _assistant("Still.")


def test_run_without_evaluator_returns_first_reply() -> None:
    fake = fakes.scripted(_assistant("Sunny."))
    weather = _weather_tool()
    helper = agent.Agent(fake, "Be helpful.", tools=[weather])

    assert helper.run([_QUESTION]) == [_assistant("Sunny.")]
    assert fake.requests == [
        fakes.Request([_SYSTEM, _QUESTION], [weather], str)
    ]


def test_run_passes_output_type() -> None:
    forecast = message.Message("assistant", _Forecast(city="Lagos"))
    fake = fakes.scripted(forecast)
    helper = agent.Agent(fake, "Be helpful.", _Forecast)

    assert helper.run([_QUESTION]) == [forecast]
    assert fake.requests[0].output_type is _Forecast


def test_run_returns_draft_that_passes_first_time() -> None:
    fake = fakes.scripted(_assistant("Sunny."))
    evaluator = _ScriptedEvaluator([_passed()])
    helper = agent.Agent(fake, "Be helpful.", evaluator=evaluator)

    assert helper.run([_QUESTION]) == [_assistant("Sunny.")]
    assert evaluator.messages == [_assistant("Sunny.")]


def test_run_sends_rejected_draft_and_feedback_back() -> None:
    fake = fakes.scripted(_assistant("Sunny."), _assistant("Sunny, 31C."))
    evaluator = _ScriptedEvaluator(
        [
            _failed("Add the temperature."),
            _passed(),
        ]
    )
    helper = agent.Agent(fake, "Be helpful.", evaluator=evaluator)

    assert helper.run([_QUESTION]) == [_assistant("Sunny, 31C.")]
    assert fake.requests[1].messages == [
        _SYSTEM,
        _QUESTION,
        _assistant("Sunny."),
        message.Message("user", "Add the temperature."),
    ]


def test_run_returns_last_draft_when_none_pass() -> None:
    fake = fakes.scripted(_assistant("one"), _assistant("two"))
    evaluator = _ScriptedEvaluator([_failed("no"), _failed("no")])
    helper = agent.Agent(
        fake, "Be helpful.", evaluator=evaluator, max_iterations=2
    )

    assert helper.run([_QUESTION]) == [_assistant("two")]
    assert len(fake.requests) == 2


def test_run_executes_tool_calls_and_asks_again() -> None:
    fake = fakes.scripted(_TOOL_DRAFT, _assistant("Sunny in Lagos."))
    helper = agent.Agent(fake, "Be helpful.", tools=[_weather_tool()])

    turn = helper.run([_QUESTION])

    assert turn == [_TOOL_DRAFT, _TOOL_RESULT, _assistant("Sunny in Lagos.")]
    assert fake.requests[1].messages == [
        _SYSTEM,
        _QUESTION,
        _TOOL_DRAFT,
        _TOOL_RESULT,
    ]


def test_run_critiques_tool_calls_and_resets_count() -> None:
    fake = fakes.scripted(
        _assistant("I don't know."),
        _TOOL_DRAFT,
        _assistant("Maybe sunny."),
        _assistant("Sunny in Lagos."),
    )
    evaluator = _ScriptedEvaluator(
        [
            _failed("Use the tool."),
            _passed(),
            _failed("Be certain."),
            _passed(),
        ]
    )
    helper = agent.Agent(
        fake,
        "Be helpful.",
        tools=[_weather_tool()],
        evaluator=evaluator,
        max_iterations=2,
    )

    turn = helper.run([_QUESTION])

    assert turn == [_TOOL_DRAFT, _TOOL_RESULT, _assistant("Sunny in Lagos.")]
    assert evaluator.messages[1] == _TOOL_DRAFT
    # Critiques of earlier drafts are not carried into later requests.
    assert fake.requests[2].messages == [
        _SYSTEM,
        _QUESTION,
        _TOOL_DRAFT,
        _TOOL_RESULT,
    ]


def test_evaluator_sees_whole_conversation_by_default() -> None:
    earlier = [message.Message("user", "Hi."), _assistant("Hello.")]
    evaluator = _ScriptedEvaluator([_passed()])
    helper = agent.Agent(
        fakes.scripted(_assistant("Sunny.")), "Be helpful.", evaluator=evaluator
    )

    helper.run([*earlier, _QUESTION])

    (draft,) = evaluator.drafts
    assert draft.context == [*earlier, _QUESTION]


def test_evaluator_sees_step_context_and_accepted_turn_messages() -> None:
    earlier = [message.Message("user", "Hi."), _assistant("Hello.")]
    fake = fakes.scripted(
        _TOOL_DRAFT, _assistant("Maybe."), _assistant("Sunny.")
    )
    evaluator = _ScriptedEvaluator([_passed(), _failed("Be sure."), _passed()])
    helper = agent.Agent(
        fake, "Be helpful.", tools=[_weather_tool()], evaluator=evaluator
    )

    helper.run([*earlier, _QUESTION], context_start=2)

    assert [item.context for item in evaluator.drafts] == [
        [_QUESTION],
        [_QUESTION, _TOOL_DRAFT, _TOOL_RESULT],
        # The rejected "Maybe." and its critique are not context.
        [_QUESTION, _TOOL_DRAFT, _TOOL_RESULT],
    ]


def test_run_raises_for_unknown_tool() -> None:
    fake = fakes.scripted(_TOOL_DRAFT)
    helper = agent.Agent(fake, "Be helpful.", tools=[_weather_tool("other")])

    with pytest.raises(exception.UnknownToolError, match="get_weather"):
        helper.run([_QUESTION])


def test_logs_keep_rejected_drafts_and_critiques() -> None:
    fake = fakes.scripted(_assistant("Sunny."), _assistant("Sunny, 31C."))
    evaluator = _ScriptedEvaluator([_failed("Add temp."), _passed()])
    helper = agent.Agent(fake, "Be helpful.", evaluator=evaluator)

    helper.run([_QUESTION])

    assert helper.logs == [
        _SYSTEM,
        _QUESTION,
        _assistant("Sunny."),
        message.Message("user", "Add temp."),
        _assistant("Sunny, 31C."),
    ]


def test_logs_have_system_message_once_and_only_new_input() -> None:
    fake = fakes.scripted(_assistant("Sunny."), _assistant("Rain later."))
    helper = agent.Agent(fake, "Be helpful.")
    tomorrow = message.Message("user", "And tomorrow?")

    helper.run([_QUESTION])
    helper.run([_QUESTION, _assistant("Sunny."), tomorrow])

    assert helper.logs == [
        _SYSTEM,
        _QUESTION,
        _assistant("Sunny."),
        tomorrow,
        _assistant("Rain later."),
    ]


def test_logs_continue_after_critiques_and_tool_calls() -> None:
    fake = fakes.scripted(
        _TOOL_DRAFT,
        _assistant("Maybe."),
        _assistant("Sunny in Lagos."),
        _assistant("Rain later."),
    )
    evaluator = _ScriptedEvaluator(
        [_passed(), _failed("Be sure."), _passed(), _passed()]
    )
    helper = agent.Agent(
        fake, "Be helpful.", tools=[_weather_tool()], evaluator=evaluator
    )
    tomorrow = message.Message("user", "And tomorrow?")

    turn = helper.run([_QUESTION])
    helper.run([_QUESTION, *turn, tomorrow])

    assert helper.logs == [
        _SYSTEM,
        _QUESTION,
        _TOOL_DRAFT,
        _TOOL_RESULT,
        _assistant("Maybe."),
        message.Message("user", "Be sure."),
        _assistant("Sunny in Lagos."),
        tomorrow,
        _assistant("Rain later."),
    ]


def test_logs_repeat_input_that_does_not_continue_and_survive_errors() -> None:
    fake = fakes.scripted(_assistant("Sunny."), _TOOL_DRAFT)
    helper = agent.Agent(fake, "Be helpful.")

    helper.run([_QUESTION])
    with pytest.raises(exception.UnknownToolError):
        helper.run([_QUESTION])

    assert helper.logs == [
        _SYSTEM,
        _QUESTION,
        _assistant("Sunny."),
        _QUESTION,
        _TOOL_DRAFT,
    ]
