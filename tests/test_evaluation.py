"""Evaluation tests.

The live test calls a real server and is skipped unless
SYNTHAID_TEST_BASE_URL, SYNTHAID_TEST_API_KEY and SYNTHAID_TEST_MODEL
are set.
"""

from collections.abc import Sequence
import json
import os

import pydantic
import pytest

from synthaid import agent
from synthaid import evaluation
from synthaid import message
from synthaid import model
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

_TEMP = evaluation.Criterion(content="States the temperature.", weight=2)
_SKY = evaluation.Criterion(content="Describes the sky.")
_HEDGE = evaluation.Criterion(content="Says 'maybe' or 'I think'.", weight=-1)
_CRITERIA = (_TEMP, _SKY, _HEDGE)
_YES = evaluation.Met.YES
_NO = evaluation.Met.NO
_NA = evaluation.Met.NA
_ASKED = message.Message("user", "What is the weather in Lagos?")
_DRAFT = agent.Draft(
    message.Message("assistant", "Sunny, 31C.", reasoning="Easy one."),
    context=[_ASKED],
)
_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)


def _verdict(
    *met: evaluation.Met,
    feedback: str = "Looks good.",
    contents: Sequence[str] | None = None,
) -> message.Message:
    """A judge reply as the server sends it: content and met, no weights."""
    if contents is None:
        contents = [item.content for item in _CRITERIA]
    return message.Message(
        "assistant",
        evaluation.Verdict(
            answers=[
                evaluation.Answer(content=content, met=value)
                for content, value in zip(contents, met, strict=True)
            ],
            feedback=feedback,
        ),
    )


_ALL_GOOD = (_YES, _YES, _NO)


def _sections(prompt: str) -> dict[str, str]:
    """Splits a judge prompt into its "Heading:" sections."""
    sections = {}
    for block in prompt.split("\n\n"):
        heading, body = block.split(":\n", 1)
        sections[heading] = body
    return sections


def test_schema_sends_content_and_met_only() -> None:
    schema = evaluation.Verdict.model_json_schema()

    assert set(schema["properties"]) == {"answers", "feedback"}
    assert set(schema["$defs"]["Answer"]["properties"]) == {"content", "met"}
    met = schema["$defs"]["Answer"]["properties"]["met"]
    assert met["$ref"] == "#/$defs/Met"
    assert schema["$defs"]["Met"]["enum"] == ["yes", "no", "n/a"]


def test_schema_never_mentions_weight() -> None:
    assert "weight" not in json.dumps(evaluation.Verdict.model_json_schema())


def test_criterion_is_unanswered_until_judged() -> None:
    assert _SKY.met is None
    assert _SKY.weight == 1.0


def test_rejects_empty_criteria() -> None:
    with pytest.raises(ValueError, match="at least one criterion"):
        evaluation.LLMJudge(fakes.scripted(), [])


def test_rejects_duplicate_contents() -> None:
    with pytest.raises(ValueError, match="Duplicate criterion contents"):
        evaluation.LLMJudge(fakes.scripted(), [_SKY, _SKY])


def test_judge_is_an_agent_with_verdict_output() -> None:
    helper = evaluation.LLMJudge(fakes.scripted(), _CRITERIA)

    assert isinstance(helper, agent.Agent)
    assert helper.output_type is evaluation.Verdict
    assert helper.tools == ()
    assert helper.evaluator is None
    assert helper.max_iterations == 1
    assert helper.criteria == _CRITERIA


def test_call_sends_criteria_and_draft_without_weights_or_reasoning() -> None:
    fake = fakes.scripted(_verdict(*_ALL_GOOD))
    helper = evaluation.LLMJudge(fake, _CRITERIA, "Judge it.")

    helper(_DRAFT)

    (request,) = fake.requests
    assert request.output_type is evaluation.Verdict
    assert request.tools == ()
    system, user = request.messages
    assert system == message.Message("system", "Judge it.")
    assert user.role == "user"
    prompt = user.text
    assert "Sunny, 31C." in prompt
    assert "Easy one." not in prompt
    assert "weight" not in prompt.lower()
    assert "-1" not in prompt


def test_call_lists_criteria_as_json_contents_in_order() -> None:
    fake = fakes.scripted(_verdict(*_ALL_GOOD))

    evaluation.LLMJudge(fake, _CRITERIA)(_DRAFT)

    sections = _sections(fake.requests[0].messages[1].text)
    assert json.loads(sections["Criteria"]) == [
        item.content for item in _CRITERIA
    ]
    assert sections["Draft"] == "Sunny, 31C."


def test_call_shows_step_conversation() -> None:
    fake = fakes.scripted(_verdict(*_ALL_GOOD))
    draft = agent.Draft(
        message.Message("assistant", "Sunny, 31C."),
        context=[
            _ASKED,
            message.Message(
                "assistant", None, reasoning="Look it up.", tool_calls=(_CALL,)
            ),
            message.Message("tool", "Sunny, 31C", tool_call_id="call-1"),
        ],
    )

    evaluation.LLMJudge(fake, _CRITERIA)(draft)

    sections = _sections(fake.requests[0].messages[1].text)
    assert list(sections) == [
        "Criteria",
        "Conversation in this step",
        "Draft",
    ]
    assert sections["Conversation in this step"] == (
        "[user] What is the weather in Lagos?\n"
        '[assistant] calls get_weather({"city": "Lagos"})\n'
        "[tool] Sunny, 31C"
    )


def test_call_leaves_out_empty_context() -> None:
    fake = fakes.scripted(_verdict(*_ALL_GOOD))

    evaluation.LLMJudge(fake, _CRITERIA)(
        agent.Draft(message.Message("assistant", "Sunny."), context=[])
    )

    sections = _sections(fake.requests[0].messages[1].text)
    assert list(sections) == ["Criteria", "Draft"]


def test_call_shows_tool_calls_in_the_draft() -> None:
    fake = fakes.scripted(_verdict(*_ALL_GOOD))
    draft = message.Message("assistant", None, tool_calls=(_CALL,))

    evaluation.LLMJudge(fake, _CRITERIA)(agent.Draft(draft, context=[]))

    prompt = fake.requests[0].messages[1].text
    assert "get_weather" in prompt
    assert '{"city": "Lagos"}' in prompt


def test_call_returns_raw_verdict_and_answered_criteria() -> None:
    reply = _verdict(_YES, _YES, _NO, feedback="Nice.")
    helper = evaluation.LLMJudge(fakes.scripted(reply), _CRITERIA)

    result = helper(_DRAFT)

    assert result.feedback == "Nice."
    assert result.metadata["verdict"] == reply.content
    # Weights come from our criteria; the server never sends them.
    assert result.metadata["criteria"] == [
        _TEMP.model_copy(update={"met": _YES}),
        _SKY.model_copy(update={"met": _YES}),
        _HEDGE.model_copy(update={"met": _NO}),
    ]


def test_logged_verdict_has_no_weights() -> None:
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(*_ALL_GOOD)), _CRITERIA
    )

    helper(_DRAFT)

    assert "weight" not in helper.logs[-1].text


def test_default_passes_when_every_criterion_is_right() -> None:
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(*_ALL_GOOD)), _CRITERIA
    )

    assert helper(_DRAFT).passed


@pytest.mark.parametrize("met", [(_NO, _YES, _NO), (_YES, _YES, _YES)])
def test_default_fails_on_a_missing_or_unwanted_criterion(
    met: tuple[evaluation.Met, ...],
) -> None:
    helper = evaluation.LLMJudge(fakes.scripted(_verdict(*met)), _CRITERIA)

    assert not helper(_DRAFT).passed


@pytest.mark.parametrize(
    ("met", "passed"),
    [
        # 2 + 0 + 0 = 2, exactly the threshold.
        ((_YES, _NO, _NO), True),
        # 2 + 1 - 1 = 2.
        ((_YES, _YES, _YES), True),
        # 0 + 1 + 0 = 1.
        ((_NO, _YES, _NO), False),
    ],
)
def test_threshold_is_the_lowest_weighted_score_that_passes(
    met: tuple[evaluation.Met, ...], passed: bool
) -> None:
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(*met)), _CRITERIA, threshold=2
    )

    assert helper(_DRAFT).passed is passed


def test_na_criterion_adds_nothing_and_is_left_out_of_default_threshold() -> (
    None
):
    # Sky (weight 1) does not apply, so the threshold is 2, not 3.
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(_YES, _NA, _NO)), _CRITERIA
    )

    assert helper(_DRAFT).passed


def test_default_threshold_is_the_sum_of_applicable_positive_weights() -> None:
    # Only Sky applies, so the threshold is 1, and Sky alone passes.
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(_NA, _YES, _NA)), _CRITERIA
    )

    assert helper(_DRAFT).passed


def test_given_threshold_ignores_na() -> None:
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(_YES, _NA, _NO)), _CRITERIA, threshold=3
    )

    assert not helper(_DRAFT).passed


_CONTENTS = [item.content for item in _CRITERIA]


@pytest.mark.parametrize(
    "reply",
    [
        _verdict(_YES, _YES, contents=_CONTENTS[:2]),
        _verdict(_YES, _YES, _NO, _YES, contents=[*_CONTENTS, "Extra."]),
        _verdict(_YES, _YES, _NO, contents=list(reversed(_CONTENTS))),
        _verdict(_YES, _YES, _NO, contents=[*_CONTENTS[:2], "Says maybe."]),
    ],
    ids=["missing", "extra", "reordered", "changed"],
)
def test_call_rejects_replies_that_do_not_answer_each_criterion_in_order(
    reply: message.Message,
) -> None:
    helper = evaluation.LLMJudge(fakes.scripted(reply), _CRITERIA)

    with pytest.raises(
        ValueError, match="Answer each criterion once, in order"
    ):
        helper(_DRAFT)


def test_call_rejects_replies_that_are_not_a_verdict() -> None:
    helper = evaluation.LLMJudge(
        fakes.scripted(message.Message("assistant", "I can't help with that.")),
        _CRITERIA,
    )

    with pytest.raises(pydantic.ValidationError):
        helper(_DRAFT)


def test_logs_keep_every_judged_draft() -> None:
    helper = evaluation.LLMJudge(
        fakes.scripted(_verdict(*_ALL_GOOD), _verdict(*_ALL_GOOD)), _CRITERIA
    )

    helper(agent.Draft(message.Message("assistant", "First."), context=[]))
    helper(agent.Draft(message.Message("assistant", "Second."), context=[]))

    assert [item.role for item in helper.logs] == [
        "system",
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    prompts = [item.text for item in helper.logs if item.role == "user"]
    assert "First." in prompts[0]
    assert "Second." in prompts[1]


def test_judge_works_as_agent_evaluator() -> None:
    critic = evaluation.LLMJudge(
        fakes.scripted(
            _verdict(_NO, _YES, _NO, feedback="Add the temperature."),
            _verdict(*_ALL_GOOD),
        ),
        _CRITERIA,
    )
    writer = fakes.scripted(
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

    result = helper(
        agent.Draft(
            message.Message("assistant", "Sunny and 31C in Lagos."),
            context=[_ASKED],
        )
    )

    criteria = result.metadata["criteria"]
    assert [item.content for item in criteria] == _CONTENTS
    assert result.passed
