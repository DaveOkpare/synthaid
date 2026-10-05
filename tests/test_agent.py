"""Native SDK generation and private reviewer feedback, with offline HTTP."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
import pytest

from agentinstruct import Agent, Judge
from agentinstruct.agent import ReviewExhausted
from agentinstruct.episode import Message
from agentinstruct.judge import Judgment
from tests.model_fixtures import Transport, client, response


@pytest.mark.asyncio
async def test_review_revises_native_output_without_mutating_history() -> None:
    reviews: list[Sequence[Mapping[str, Any]]] = []
    key = "input"

    async def sample(request: httpx.Request) -> httpx.Response:
        history = json.loads(request.content)[key]
        corrected = history[-1]["content"] == "Use correct"
        return response("correct" if corrected else "wrong")

    def review(messages: Sequence[Mapping[str, Any]]) -> Judgment:
        reviews.append(messages)
        return Judgment('"correct"' in json.dumps(messages[-1]), "Use correct")

    transport = Transport(sample, sample)
    history = [Message(role="user", content="Question")]
    async with client(transport) as borrowed:
        agent = Agent("model", "Be accurate", reviewer=Judge(check=review))
        result = await agent.generate(history, client=borrowed, temperature=0.2)
        assert not borrowed.is_closed()
    assert result.output_text == "correct"
    assert history == [{"role": "user", "content": "Question"}]
    requests = [json.loads(request.content) for request in transport.requests]
    assert requests[0][key] == [{"role": "system", "content": "Be accurate"}, *history]
    assert requests[1][key][-1] == {"role": "user", "content": "Use correct"}
    assert requests[1][key][-2] == reviews[0][-1]
    assert all(request["temperature"] == 0.2 for request in requests)
    assert [len(review) for review in reviews] == [3, 5]
    assert "wrong" in json.dumps(agent.history)
    assert agent.history[-2] == {"role": "user", "content": "Use correct"}
    assert '"correct"' in json.dumps(agent.history[-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("max_revisions", [0, 1, 3])
async def test_revision_limit(max_revisions: int) -> None:
    transport = Transport(*(response("draft") for _ in range(max_revisions + 1)))
    agent = Agent(
        "model", reviewer=Judge(check=lambda m: False), max_revisions=max_revisions
    )
    async with client(transport) as borrowed:
        with pytest.raises(ReviewExhausted):
            await agent.generate([], client=borrowed)
    assert len(transport.requests) == max_revisions + 1


@pytest.mark.asyncio
async def test_separate_agents_keep_concurrent_feedback_private() -> None:
    async def sample(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0)
        return response(json.loads(request.content)["input"][-1]["content"])

    reviewer = Judge(
        check=lambda m: Judgment(
            m[-1]["content"][0]["text"] == "fixed " + m[1]["content"],
            "fixed " + m[1]["content"],
        )
    )
    agents = [Agent("model", reviewer=reviewer) for _ in range(2)]
    transport = Transport(sample, sample, sample, sample)
    async with client(transport) as borrowed:
        results = await asyncio.gather(
            *(
                agent.generate([{"role": "user", "content": value}], client=borrowed)
                for agent, value in zip(agents, ("one", "two"), strict=True)
            )
        )
    assert [r.output_text for r in results] == ["fixed one", "fixed two"]
    assert "two" not in json.dumps(agents[0].history)
    assert "one" not in json.dumps(agents[1].history)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_revisions", [-1, True, 1.5])
async def test_invalid_revision_budget(max_revisions: Any) -> None:
    with pytest.raises(ValueError, match="max_revisions"):
        await Agent("model", max_revisions=max_revisions).generate([])


@pytest.mark.asyncio
async def test_responses_keeps_reasoning_when_revising() -> None:
    reasoning = {
        "id": "rs_1",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "Check the answer."}],
        "encrypted_content": "opaque",
    }
    draft = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "wrong", "annotations": []}],
    }
    transport = Transport(
        response(output=[reasoning, draft]),
        response("correct"),
    )
    judge = Judge(
        check=lambda m: Judgment('"correct"' in json.dumps(m[-1]), "Use correct")
    )
    async with client(transport) as borrowed:
        result = await Agent("model", reviewer=judge).generate(
            [],
            client=borrowed,
            store=False,
            reasoning={"effort": "medium", "summary": "auto"},
            include=["reasoning.encrypted_content"],
        )
    assert result.output_text == "correct"
    for request in transport.requests:
        body = json.loads(request.content)
        assert body["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert body["include"] == ["reasoning.encrypted_content"]
    assert json.loads(transport.requests[1].content)["input"][1:3] == [reasoning, draft]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["system", "developer"])
async def test_explicit_instruction_is_forwarded(role: str) -> None:
    history = [{"role": role, "content": "Override"}, {"role": "user", "content": "Hi"}]
    transport = Transport(response())
    async with client(transport) as borrowed:
        await Agent("model", "Default").generate(history, client=borrowed)
    assert json.loads(transport.requests[0].content)["input"] == history


@pytest.mark.asyncio
async def test_tool_review_supplies_feedback_without_running_tools() -> None:
    from agentinstruct import Tool
    from tests.model_fixtures import function

    effects: list[bool] = []

    async def lookup(arguments: Any) -> None:
        effects.append(True)

    async def sample(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        history = body["input"]
        revised = history[-1]["content"] == "Use safe"
        call = function(
            "safe" if revised else "unsafe", "safe" if revised else "unsafe"
        )
        if revised:
            rejected = history[-2]
            assert rejected["role"] == "assistant"
            assert "call_id" not in rejected
            assert "unsafe" in rejected["content"]
        return response("", output=[call])

    judge = Judge(
        check=lambda m: Judgment("unsafe" not in json.dumps(m[-1]), "Use safe")
    )
    transport = Transport(sample, sample)
    tool = Tool(lookup)
    async with client(transport) as borrowed:
        raw = await Agent("model", tools=[tool], reviewer=judge).generate(
            [], client=borrowed
        )
    assert "safe" in raw.model_dump_json() and not effects
    assert json.loads(transport.requests[0].content)["tools"] == [tool.schema()]
