"""Evaluation tests.

The live test calls a real server and is skipped unless
SYNTHAID_TEST_BASE_URL, SYNTHAID_TEST_API_KEY and SYNTHAID_TEST_MODEL
are set.
"""

from collections.abc import Sequence
import dataclasses
import json
import os

import pydantic
import pytest

from synthaid import agent
from synthaid import evaluation
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

_TEMP = evaluation.Criterion(
    title="Temperature", content="States the temperature.", weight=2
)
_SKY = evaluation.Criterion(title="Sky", content="Describes the sky.")
_HEDGE = evaluation.Criterion(
    title="Hedging", content="Says 'maybe' or 'I think'.", weight=-1
)
_CRITERIA = (_TEMP, _SKY, _HEDGE)
_DRAFT = message.Message("assistant", "Sunny, 31C.", reasoning="Easy one.")


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


def _model(*replies: message.Message) -> _ScriptedModel:
    return _ScriptedModel(
        model_name="fake", base_url="http://unused", replies=list(replies)
    )


def _answer(
    met: dict[str, bool], feedback: str = "Looks good."
) -> message.Message:
    """A judge reply as the server sends it: no weights, any order."""
    by_title = {item.title: item for item in _CRITERIA}
    verdict = evaluation.Verdict(
        criteria=[
            evaluation.Criterion(
                title=title, content=by_title[title].content, met=value
            )
            for title, value in met.items()
        ],
        feedback=feedback,
    )
    return message.Message("assistant", verdict)


_ALL_GOOD = {"Temperature": True, "Sky": True, "Hedging": False}


def test_schema_sends_title_content_and_met_only() -> None:
    schema = evaluation.Verdict.model_json_schema()

    assert set(schema["properties"]) == {"criteria", "feedback"}
    assert set(schema["$defs"]["Criterion"]["properties"]) == {
        "title",
        "content",
        "met",
    }
    met = schema["$defs"]["Criterion"]["properties"]["met"]
    assert met["type"] == "boolean"


def test_schema_never_mentions_weight() -> None:
    assert "weight" not in json.dumps(evaluation.Verdict.model_json_schema())


def test_criterion_is_unanswered_until_judged() -> None:
    assert _SKY.met is None
    assert _SKY.weight == 1.0


def test_rejects_empty_criteria() -> None:
    with pytest.raises(ValueError, match="at least one criterion"):
        evaluation.LLMJudge(_model(), [])


def test_rejects_duplicate_titles() -> None:
    with pytest.raises(ValueError, match="Duplicate criterion titles"):
        evaluation.LLMJudge(_model(), [_SKY, _SKY])


def test_judge_is_an_agent_with_verdict_output() -> None:
    helper = evaluation.LLMJudge(_model(), _CRITERIA)

    assert isinstance(helper, agent.Agent)
    assert helper.output_type is evaluation.Verdict
    assert helper.tools == ()
    assert helper.evaluator is None
    assert helper.max_iterations == 1
    assert helper.criteria == _CRITERIA


def test_call_sends_criteria_and_draft_without_weights_or_reasoning() -> None:
    fake = _model(_answer(_ALL_GOOD))
    helper = evaluation.LLMJudge(fake, _CRITERIA, "Judge it.")

    helper(_DRAFT)

    (request,) = fake.requests
    assert request.output_type is evaluation.Verdict
    assert request.tools == ()
    system, user = request.messages
    assert system == message.Message("system", "Judge it.")
    assert user.role == "user"
    prompt = user.text
    for item in _CRITERIA:
        assert item.title in prompt
        assert item.content in prompt
    assert "Sunny, 31C." in prompt
    assert "Easy one." not in prompt
    assert "weight" not in prompt.lower()
    assert "-1" not in prompt


def test_call_shows_tool_calls_in_the_draft() -> None:
    fake = _model(_answer(_ALL_GOOD))
    call = message.ToolCall(
        id="call-1", name="get_weather", arguments={"city": "Lagos"}
    )
    draft = message.Message("assistant", None, tool_calls=(call,))

    evaluation.LLMJudge(fake, _CRITERIA)(draft)

    prompt = fake.requests[0].messages[1].text
    assert "get_weather" in prompt
    assert '{"city": "Lagos"}' in prompt


def test_call_returns_feedback_and_answered_criteria_in_order() -> None:
    reply = _answer(
        {"Hedging": False, "Sky": True, "Temperature": True}, "Nice."
    )
    helper = evaluation.LLMJudge(_model(reply), _CRITERIA)

    result = helper(_DRAFT)

    assert result.feedback == "Nice."
    verdict = result.metadata["verdict"]
    assert verdict.feedback == "Nice."
    # Weights come back from our criteria; the server never sends them.
    assert verdict.criteria == [
        _TEMP.model_copy(update={"met": True}),
        _SKY.model_copy(update={"met": True}),
        _HEDGE.model_copy(update={"met": False}),
    ]


def test_default_passes_when_every_criterion_is_right() -> None:
    helper = evaluation.LLMJudge(_model(_answer(_ALL_GOOD)), _CRITERIA)

    assert helper(_DRAFT).passed


@pytest.mark.parametrize(
    "met",
    [
        {"Temperature": False, "Sky": True, "Hedging": False},
        {"Temperature": True, "Sky": True, "Hedging": True},
    ],
)
def test_default_fails_on_a_missing_or_unwanted_criterion(
    met: dict[str, bool],
) -> None:
    helper = evaluation.LLMJudge(_model(_answer(met)), _CRITERIA)

    assert not helper(_DRAFT).passed


@pytest.mark.parametrize(
    ("met", "passed"),
    [
        # 2 + 0 + 0 = 2, exactly the threshold.
        ({"Temperature": True, "Sky": False, "Hedging": False}, True),
        # 2 + 1 - 1 = 2.
        ({"Temperature": True, "Sky": True, "Hedging": True}, True),
        # 0 + 1 + 0 = 1.
        ({"Temperature": False, "Sky": True, "Hedging": False}, False),
    ],
)
def test_threshold_is_the_lowest_weighted_score_that_passes(
    met: dict[str, bool], passed: bool
) -> None:
    helper = evaluation.LLMJudge(_model(_answer(met)), _CRITERIA, threshold=2)

    assert helper(_DRAFT).passed is passed


def test_custom_passes_gets_answered_criteria_and_threshold() -> None:
    seen: list[tuple[list[evaluation.Criterion], float]] = []

    def always_pass(
        criteria: Sequence[evaluation.Criterion], threshold: float
    ) -> bool:
        seen.append((list(criteria), threshold))
        return True

    helper = evaluation.LLMJudge(
        _model(_answer({"Temperature": False, "Sky": False, "Hedging": True})),
        _CRITERIA,
        passes=always_pass,
        threshold=7,
    )

    assert helper(_DRAFT).passed
    ((criteria, threshold),) = seen
    assert [item.met for item in criteria] == [False, False, True]
    assert [item.weight for item in criteria] == [2, 1, -1]
    assert threshold == 7


def test_custom_passes_gets_default_threshold() -> None:
    thresholds: list[float] = []

    def record(
        criteria: Sequence[evaluation.Criterion], threshold: float
    ) -> bool:
        thresholds.append(threshold)
        return False

    helper = evaluation.LLMJudge(
        _model(_answer(_ALL_GOOD)), _CRITERIA, passes=record
    )

    assert not helper(_DRAFT).passed
    # The sum of the positive weights.
    assert thresholds == [3]


def _reply(*titles: str) -> message.Message:
    return message.Message(
        "assistant",
        evaluation.Verdict(
            criteria=[
                evaluation.Criterion(title=title, content="", met=True)
                for title in titles
            ],
            feedback="",
        ),
    )


@pytest.mark.parametrize(
    "reply",
    [
        _reply("Temperature", "Sky"),
        _reply("Temperature", "Sky", "Hedging", "Extra"),
        _reply("Temperature", "Sky", "Hedging", "Sky"),
    ],
    ids=["missing", "extra", "repeated"],
)
def test_call_rejects_replies_that_do_not_answer_each_criterion_once(
    reply: message.Message,
) -> None:
    helper = evaluation.LLMJudge(_model(reply), _CRITERIA)

    with pytest.raises(
        pydantic.ValidationError, match="Answer each criterion once"
    ):
        helper(_DRAFT)


def test_call_rejects_replies_that_are_not_a_verdict() -> None:
    helper = evaluation.LLMJudge(
        _model(message.Message("assistant", "I can't help with that.")),
        _CRITERIA,
    )

    with pytest.raises(pydantic.ValidationError):
        helper(_DRAFT)


def test_verdict_accepts_any_criteria_without_context() -> None:
    verdict = evaluation.Verdict(
        criteria=[evaluation.Criterion(title="Anything", content="")],
        feedback="",
    )

    assert [item.title for item in verdict.criteria] == ["Anything"]


def test_logs_keep_every_judged_draft() -> None:
    helper = evaluation.LLMJudge(
        _model(_answer(_ALL_GOOD), _answer(_ALL_GOOD)), _CRITERIA
    )

    helper(message.Message("assistant", "First."))
    helper(message.Message("assistant", "Second."))

    prompts = [item.text for item in helper.logs if item.role == "user"]
    assert len(prompts) == 2
    assert "First." in prompts[0]
    assert "Second." in prompts[1]


def test_judge_works_as_agent_evaluator() -> None:
    critic = evaluation.LLMJudge(
        _model(
            _answer(
                {"Temperature": False, "Sky": True, "Hedging": False},
                "Add the temperature.",
            ),
            _answer(_ALL_GOOD),
        ),
        _CRITERIA,
    )
    writer = _model(
        message.Message("assistant", "Sunny."),
        message.Message("assistant", "Sunny, 31C."),
    )
    helper = agent.Agent(writer, "Be helpful.", evaluator=critic)

    turn = helper.run([message.Message("user", "Weather in Lagos?")])

    assert turn == [message.Message("assistant", "Sunny, 31C.")]
    assert writer.requests[1].messages[-1] == message.Message(
        "user", "Add the temperature."
    )


@live
def test_live_judge() -> None:
    live_model = model.Model(
        model_name=os.environ["SYNTHAID_TEST_MODEL"],
        base_url=os.environ["SYNTHAID_TEST_BASE_URL"],
        api_key=os.environ["SYNTHAID_TEST_API_KEY"],
    )
    helper = evaluation.LLMJudge(live_model, _CRITERIA)

    result = helper(message.Message("assistant", "Sunny and 31C in Lagos."))

    verdict = result.metadata["verdict"]
    assert [item.title for item in verdict.criteria] == [
        "Temperature",
        "Sky",
        "Hedging",
    ]
    assert result.passed
