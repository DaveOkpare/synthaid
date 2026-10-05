"""Rubric evaluation through the real SDK with offline model responses."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import APIStatusError
from pydantic import ValidationError

from agentinstruct import Agent, Judge, Runner, Task
from agentinstruct.judge import Criterion, Rubric
from tests.model_fixtures import Transport, assessment, client, response


@pytest.mark.asyncio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("threshold,passed", [(0.74, True), (0.75, False)])
async def test_code_checks_share_weighting_and_threshold_without_model_calls(
    asynchronous: bool, threshold: float, passed: bool
) -> None:
    rubric = Rubric([Criterion("Correct", 3), Criterion("Clear", 1)], threshold)

    def check(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {"criteria": [True, False], "feedback": messages[-1]["content"]}

    async def async_check(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        await asyncio.sleep(0)
        return check(messages)

    transport = Transport()
    async with client(transport) as borrowed:
        judge = Judge(
            rubric, client=borrowed, check=async_check if asynchronous else check
        )
        results = await asyncio.gather(
            *(
                judge.evaluate([{"role": "assistant", "content": str(i)}])
                for i in range(2)
            )
        )
    assert [result.feedback for result in results] == ["0", "1"]
    assert all(result.score == 0.75 and result.passed is passed for result in results)
    assert not transport.requests


@pytest.mark.asyncio
async def test_code_check_feedback_is_optional_and_errors_propagate() -> None:
    rubric = Rubric([Criterion("Correct")], 0.5)
    result = await Judge(rubric, check=lambda messages: {"criteria": [True]}).evaluate(
        []
    )
    assert result.passed and result.feedback == ""
    error = OSError("Check failed")

    def failing(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        raise error

    with pytest.raises(OSError) as caught:
        await Judge(rubric, check=failing).evaluate([])
    assert caught.value is error


@pytest.mark.asyncio
async def test_code_feedback_revises_agent_and_verifies_the_published_reply(
    tmp_path: Path,
) -> None:
    reviewed = []

    def check(messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        content = messages[-1]["content"]
        text = content if isinstance(content, str) else content[0]["text"]
        reviewed.append(text)
        return {"criteria": [text == "42"], "feedback": "Use 42."}

    judge = Judge(Rubric([Criterion("Answer six times seven.")], 0.9), check=check)
    task = Task(agents={"assistant": Agent("model", reviewer=judge)}, verifier=judge)
    transport = Transport(response("Wrong"), response("42"))
    async with client(transport) as borrowed:
        [episode] = await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert reviewed == ["Wrong", "42", "42"]
    assert episode.messages == [{"role": "assistant", "content": "42"}]
    assert episode.verification is not None and episode.verification.score == 1.0
    assert json.loads(transport.requests[1].content)["input"][-1] == {
        "role": "user",
        "content": "Use 42.",
    }
    assert len(transport.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "threshold,passed", [(0.74, True), (0.75, False), (0.76, False)]
)
async def test_weighted_score_uses_strict_threshold(
    threshold: float, passed: bool
) -> None:
    rubric = Rubric(
        [
            Criterion("The arithmetic is correct.", 3),
            Criterion("The explanation is clear.", 1),
        ],
        threshold,
    )
    messages = [{"role": "assistant", "content": "Six times seven is 42."}]
    transport = Transport(assessment(True, False, feedback="Explain the steps."))
    async with client(transport) as borrowed:
        result = await Judge(rubric, "judge", borrowed).evaluate(messages)
        assert not borrowed.is_closed()
    assert result.score == 0.75 and result.passed is passed
    assert result.feedback == "Explain the steps."
    request = transport.requests[0]
    body = json.loads(request.content)
    assert request.url.path == "/v1/responses" and body["model"] == "judge"
    assert body["store"] is False
    assert json.loads(body["input"]) == {
        "criteria": [criterion.context for criterion in rubric.criteria],
        "messages": messages,
    }
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["properties"]["criteria"]["items"] == {
        "type": "boolean"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("passed,threshold", [(True, 1.0), (False, 0.0)])
async def test_threshold_equality_rejects_at_score_endpoints(
    passed: bool, threshold: float
) -> None:
    async with client(Transport(assessment(passed))) as borrowed:
        result = await Judge(
            Rubric([Criterion("Correct")], threshold), "judge", borrowed
        ).evaluate([])
    assert result.score == threshold and result.passed is False
    assert result.feedback == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["model", "code"])
@pytest.mark.parametrize("grades", [[], [True, False], ["yes"], [1]])
async def test_invalid_or_missing_grades_do_not_produce_a_judgment(
    grades: list[object],
    source: str,
) -> None:
    transport = Transport(response(json.dumps({"criteria": grades, "feedback": ""})))
    async with client(transport) as borrowed:
        judge = Judge(Rubric([Criterion("Correct")], 0.5), "judge", borrowed)
        if source == "code":
            judge.check = lambda messages: {"criteria": grades}
        with pytest.raises((ValueError, ValidationError)):
            await judge.evaluate([])
    assert len(transport.requests) == (1 if source == "model" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["refusal", "length"])
async def test_unfinished_or_refused_evaluation_is_not_accepted(failure: str) -> None:
    transport = Transport(
        response('{"criteria":[true],"feedback":""}', failure=failure)
    )
    async with client(transport) as borrowed:
        judge = Judge(Rubric([Criterion("Correct")], 0.5), "judge", borrowed)
        with pytest.raises(ValueError, match="completed assessment"):
            await judge.evaluate([])


@pytest.mark.asyncio
async def test_sdk_errors_propagate_without_judge_error_wrappers() -> None:
    transport = Transport(httpx.Response(500, json={"error": {"message": "failed"}}))
    async with client(transport) as borrowed:
        judge = Judge(Rubric([Criterion("Correct")], 0.5), "judge", borrowed)
        with pytest.raises(APIStatusError) as caught:
            await judge.evaluate([])
    assert caught.value.status_code == 500
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_same_judge_reviews_revisions_and_verifies_public_reply(
    tmp_path: Path,
) -> None:
    transport = Transport(
        response("Wrong"),
        assessment(False, feedback="Use 42."),
        response("42"),
        assessment(True),
        assessment(True, feedback="Correct."),
    )
    async with client(transport) as borrowed:
        judge = Judge(
            Rubric([Criterion("Answer six times seven.")], 0.9), "judge", borrowed
        )
        task = Task(
            agents={"assistant": Agent("model", reviewer=judge)}, verifier=judge
        )
        [episode] = await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert episode.messages == [{"role": "assistant", "content": "42"}]
    requests = [json.loads(request.content) for request in transport.requests]
    assert requests[2]["input"][-1] == {"role": "user", "content": "Use 42."}
    assert json.loads(requests[-1]["input"])["messages"] == episode.messages
    assert episode.path is not None
    saved = json.loads(episode.path.read_text())
    assert saved["verification"] == {
        "passed": True,
        "score": 1.0,
        "feedback": "Correct.",
    }
    assert "Wrong" not in episode.path.read_text()
