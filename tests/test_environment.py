"""UserSimEnv exchanges messages, records the conversation and optionally verifies."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import pytest

from agentinstruct import Agent, Runner, Task
from agentinstruct.judge import Judgment
from tests.model_fixtures import Transport, client, response


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("user", "assistant"), ("assistant", "user")])
@pytest.mark.parametrize("max_turns", [3, 4])
async def test_agents_take_turns_with_recorded_history(
    tmp_path: Path, order: tuple[Literal["user", "assistant"], ...], max_turns: int
) -> None:
    transport = Transport(*(response(f"Turn {i + 1}") for i in range(max_turns)))
    shared = Agent("model", instruction="Talk about the topic")
    task = Task(
        agents=dict.fromkeys(order, shared),
        input={"topic": "fractions"},
        max_turns=max_turns,
    )
    async with client(transport) as borrowed:
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
    expected = (list(order) * max_turns)[:max_turns]
    assert [m["role"] for m in task.episode.messages] == expected
    for index, request in enumerate(transport.requests):
        history = json.loads(request.content)["input"]
        assert [m["content"] for m in history[:2]] == [
            "Talk about the topic",
            '{"topic": "fractions"}',
        ]
        for actual, published in zip(
            history[2:], task.episode.messages[:index], strict=True
        ):
            if published["role"] == expected[index]:
                assert actual["role"] == "assistant"
                assert actual["content"][0]["text"] == published["content"]
            else:
                assert actual == {"role": "user", "content": published["content"]}
    assert not task.episode.verification
    loaded = json.loads((tmp_path / task.episode.id / "trace.json").read_text())
    assert [m["content"] for m in loaded["messages"]] == [
        m["content"] for m in task.episode.messages
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("dialogue", [False, True])
@pytest.mark.parametrize("verdict", [None, False, True])
async def test_completion_and_optional_verification(
    tmp_path: Path, dialogue: bool, verdict: bool | None
) -> None:
    verified: list[Sequence[Mapping[str, Any]]] = []

    class Verifier:
        async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
            assert not (tmp_path / task.episode.id / "trace.json").exists()
            verified.append(messages)
            return Judgment(bool(verdict))

    agent = Agent("model")
    task = Task(
        agents={"user": agent, "assistant": agent}
        if dialogue
        else {"assistant": agent},
        verifier=Verifier() if verdict is not None else None,
        max_turns=2,
    )
    async with client(Transport(response(), response())) as borrowed:
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert len(task.episode.messages) == (2 if dialogue else 1)
    assert verified == ([] if verdict is None else [tuple(task.episode.messages)])
    assert (
        task.episode.verification.passed if task.episode.verification else None
    ) is verdict


@pytest.mark.parametrize("max_turns", [0, -1, True, 1.5])
def test_invalid_turn_limits_are_rejected(max_turns: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        Task(agents={"assistant": Agent("model")}, max_turns=max_turns)


@pytest.mark.asyncio
async def test_only_published_reply_crosses_agents_with_private_tool_history(
    tmp_path: Path,
) -> None:
    from agentinstruct import Tool
    from tests.model_fixtures import function

    async def lookup(arguments: Mapping[str, Any]) -> dict[str, str]:
        assert arguments == {"value": "PRIVATE_QUERY"}
        return {"result": "PRIVATE_RESULT"}

    tool = Tool(lookup)
    task = Task(
        agents={
            "user": Agent("user-model"),
            "assistant": Agent("assistant-model", tools=[tool]),
        },
        max_turns=2,
    )
    assistant, user = task.agents["assistant"], task.agents["user"]
    call = function("private-call", "PRIVATE_QUERY")
    transport = Transport(
        response("", output=[call]),
        response("Public answer"),
        response("Public follow-up"),
        response("Public conclusion"),
    )
    async with client(transport) as borrowed:
        raw = await assistant.generate(
            [{"role": "user", "content": "PRIVATE_REQUEST"}], client=borrowed
        )
        proposal = raw.output[0]
        result = json.dumps(await tool.call(json.loads(proposal.arguments)))
        tool_result = {
            "type": "function_call_output",
            "call_id": "private-call",
            "output": result,
        }
        await assistant.generate([tool_result], client=borrowed)
        task.episode.messages.extend(
            [
                {"role": "user", "content": "OLDER_PUBLISHED_MESSAGE"},
                {"role": "assistant", "content": "Public answer"},
            ]
        )
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
    key = "input"
    user_request = json.loads(transport.requests[2].content)[key]
    assert user_request == [
        {"role": "system", "content": ""},
        {"role": "user", "content": "Public answer"},
    ]
    assistant_request = json.loads(transport.requests[3].content)[key]
    assert tool_result in assistant_request
    assert assistant_request[-1] == {"role": "user", "content": "Public follow-up"}
    assert "PRIVATE_QUERY" in json.dumps(assistant_request)
    assert "PRIVATE_" not in json.dumps(user.history)
    assert "OLDER_PUBLISHED_MESSAGE" not in json.dumps(user.history)
    assert task.episode.path is not None
    assert "PRIVATE_" not in task.episode.path.read_text()
    assert [m["content"] for m in task.episode.messages[-3:]] == [
        "Public answer",
        "Public follow-up",
        "Public conclusion",
    ]


def test_tasks_and_participants_start_with_separate_fresh_histories() -> None:
    template = Agent("model", history=[{"role": "user", "content": "old task"}])
    one = Task(agents={"user": template, "assistant": template})
    two = Task(agents={"assistant": template})
    user, assistant, other = (
        one.agents["user"],
        one.agents["assistant"],
        two.agents["assistant"],
    )
    assert all(
        agent is not template and agent.history == []
        for agent in (user, assistant, other)
    )
    assistant.history.append({"role": "assistant", "content": "private"})
    assert user.history == other.history == []
    assert template.history == [{"role": "user", "content": "old task"}]
