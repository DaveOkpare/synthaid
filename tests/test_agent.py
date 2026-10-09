from collections.abc import Sequence
import dataclasses

import pydantic
import pytest

from synthaid import agent
from synthaid import evaluation
from synthaid import exception
from synthaid import message
from synthaid import model
from synthaid import tool

_SYSTEM = message.Message("system", "Be helpful.")
_QUESTION = message.Message("user", "What is the weather in Lagos?")
_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)


class _Forecast(pydantic.BaseModel):
    city: str


@dataclasses.dataclass(frozen=True)
class _Request:
    messages: list[message.Message]
    tools: Sequence[tool.Tool]
    output_type: type[str] | type[pydantic.BaseModel]


@dataclasses.dataclass(frozen=True)
class _ScriptedModel(model.Model):
    """Returns `replies` in order and records every request."""

    replies: list[message.Message] = dataclasses.field(default_factory=list)
    requests: list[_Request] = dataclasses.field(default_factory=list)

    def generate(
        self,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        self.requests.append(_Request(list(messages), tools, output_type))
        return self.replies.pop(0)


def _passed() -> evaluation.EvalResult:
    return evaluation.EvalResult("", score=1.0, passed=True)


def _failed(feedback: str) -> evaluation.EvalResult:
    return evaluation.EvalResult(feedback, score=0.0, passed=False)


@dataclasses.dataclass
class _ScriptedEvaluator:
    """Returns `results` in order and records every draft it sees."""

    results: list[evaluation.EvalResult]
    drafts: list[message.Message] = dataclasses.field(default_factory=list)

    def __call__(self, draft: message.Message) -> evaluation.EvalResult:
        self.drafts.append(draft)
        return self.results.pop(0)


def _model(*replies: message.Message) -> _ScriptedModel:
    return _ScriptedModel(
        model_name="fake", base_url="http://unused", replies=list(replies)
    )


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
        agent.Agent(_model(), "Be helpful.", _Forecast, tools=[_weather_tool()])


def test_rejects_duplicate_tool_names() -> None:
    with pytest.raises(ValueError, match="get_weather"):
        agent.Agent(
            _model(), "Be helpful.", tools=[_weather_tool(), _weather_tool()]
        )


def test_rejects_max_iterations_below_one() -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        agent.Agent(_model(), "Be helpful.", max_iterations=0)


def test_run_without_evaluator_returns_first_reply() -> None:
    fake = _model(_assistant("Sunny."))
    weather = _weather_tool()
    helper = agent.Agent(fake, "Be helpful.", tools=[weather])

    assert helper.run([_QUESTION]) == [_assistant("Sunny.")]
    assert fake.requests == [_Request([_SYSTEM, _QUESTION], [weather], str)]


def test_run_passes_output_type() -> None:
    forecast = message.Message("assistant", _Forecast(city="Lagos"))
    fake = _model(forecast)
    helper = agent.Agent(fake, "Be helpful.", _Forecast)

    assert helper.run([_QUESTION]) == [forecast]
    assert fake.requests[0].output_type is _Forecast


def test_run_returns_draft_that_passes_first_time() -> None:
    fake = _model(_assistant("Sunny."))
    evaluator = _ScriptedEvaluator([_passed()])
    helper = agent.Agent(fake, "Be helpful.", evaluator=evaluator)

    assert helper.run([_QUESTION]) == [_assistant("Sunny.")]
    assert evaluator.drafts == [_assistant("Sunny.")]


def test_run_sends_rejected_draft_and_feedback_back() -> None:
    fake = _model(_assistant("Sunny."), _assistant("Sunny, 31C."))
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
    fake = _model(_assistant("one"), _assistant("two"))
    evaluator = _ScriptedEvaluator([_failed("no"), _failed("no")])
    helper = agent.Agent(
        fake, "Be helpful.", evaluator=evaluator, max_iterations=2
    )

    assert helper.run([_QUESTION]) == [_assistant("two")]
    assert len(fake.requests) == 2


def test_run_executes_tool_calls_and_asks_again() -> None:
    fake = _model(_TOOL_DRAFT, _assistant("Sunny in Lagos."))
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
    fake = _model(
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
    assert evaluator.drafts[1] == _TOOL_DRAFT
    # Critiques of earlier drafts are not carried into later requests.
    assert fake.requests[2].messages == [
        _SYSTEM,
        _QUESTION,
        _TOOL_DRAFT,
        _TOOL_RESULT,
    ]


def test_run_raises_for_unknown_tool() -> None:
    fake = _model(_TOOL_DRAFT)
    helper = agent.Agent(fake, "Be helpful.", tools=[_weather_tool("other")])

    with pytest.raises(exception.UnknownToolError, match="get_weather"):
        helper.run([_QUESTION])


def test_logs_keep_rejected_drafts_and_critiques() -> None:
    fake = _model(_assistant("Sunny."), _assistant("Sunny, 31C."))
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


def test_logs_append_across_runs_and_survive_errors() -> None:
    fake = _model(_assistant("Sunny."), _TOOL_DRAFT)
    helper = agent.Agent(fake, "Be helpful.")

    helper.run([_QUESTION])
    with pytest.raises(exception.UnknownToolError):
        helper.run([_QUESTION])

    assert helper.logs == [
        _SYSTEM,
        _QUESTION,
        _assistant("Sunny."),
        _SYSTEM,
        _QUESTION,
        _TOOL_DRAFT,
    ]
