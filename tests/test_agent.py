"""Direct generation owns review, without requiring Task execution or recording."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from agentinstruct import Agent, Judge, Tool
from agentinstruct.agent import ReviewExhausted
from agentinstruct.episode import FunctionCall, Message, ToolCall
from agentinstruct.judge import Judgment
from tests.model_fixtures import Transport, client, response


@pytest.mark.asyncio
async def test_direct_model_generation_uses_instructions_and_private_feedback() -> None:
    reviews: list[Sequence[Message]] = []

    def review(messages: Sequence[Message]) -> Judgment:
        reviews.append(messages)
        return Judgment(messages[-1].content == "correct", "Use correct")

    transport = Transport(
        response("chat_completions", "wrong"), response("chat_completions", "correct")
    )
    history = [Message("user", "Question")]
    async with client(transport) as borrowed:
        agent = Agent("model", "Be accurate", reviewer=Judge(check=review))
        result = await agent.generate(history, client=borrowed)
        assert not borrowed.is_closed()
    assert result.content == "correct"
    assert history == [Message("user", "Question")]
    requests = [json.loads(request.content) for request in transport.requests]
    key = "messages"
    assert requests[0][key] == [
        {"role": "system", "content": "Be accurate"},
        {"role": "user", "content": "Question"},
    ]
    assert requests[1][key][-2:] == [
        {"role": "assistant", "content": "wrong"},
        {"role": "user", "content": "Use correct"},
    ]
    assert [[m.content for m in review] for review in reviews] == [
        ["Be accurate", "Question", "wrong"],
        ["Be accurate", "Question", "correct"],
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("max_revisions", [0, 1, 3])
async def test_direct_generation_stops_at_revision_limit(max_revisions: int) -> None:
    drafts: list[Sequence[Message]] = []

    class Rejected:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            drafts.append(history)
            return Message("assistant", "draft")

    agent = Agent(
        generator=Rejected(),
        reviewer=Judge(check=lambda messages: False),
        max_revisions=max_revisions,
    )
    with pytest.raises(ReviewExhausted):
        await agent.generate([])
    assert len(drafts) == max_revisions + 1


@pytest.mark.asyncio
async def test_unreviewed_direct_generation_samples_once_without_tool_effects() -> None:
    effects: list[str] = []
    samples: list[Sequence[Message]] = []

    async def effect(arguments: Mapping[str, Any]) -> Any:
        effects.append("executed")
        return {}

    class Propose:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            samples.append(history)
            return Message(
                "assistant", tool_calls=(ToolCall("id", FunctionCall("effect")),)
            )

    agent = Agent(generator=Propose(), tools=[Tool(effect)], max_revisions=10)
    result = await agent.generate([])
    assert result.tool_calls[0].function.name == "effect"
    assert len(samples) == 1 and (not effects)


@pytest.mark.asyncio
async def test_concurrent_generation_does_not_share_drafts_or_feedback() -> None:

    class Revise:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            await asyncio.sleep(0)
            return Message("assistant", history[-1].content)

    agent = Agent(
        generator=Revise(),
        reviewer=Judge(
            check=lambda messages: Judgment(
                messages[-1].content == "fixed " + messages[1].content,
                "fixed " + messages[1].content,
            )
        ),
    )
    results = await asyncio.gather(
        agent.generate([Message("user", "one")]),
        agent.generate([Message("user", "two")]),
    )
    assert [result.content for result in results] == ["fixed one", "fixed two"]


@pytest.mark.asyncio
@pytest.mark.parametrize("max_revisions", [-1, True, 1.5])
async def test_invalid_revision_budget_fails_before_sampling(
    max_revisions: Any,
) -> None:
    with pytest.raises(ValueError, match="max_revisions"):
        await Agent(max_revisions=max_revisions).generate([])
