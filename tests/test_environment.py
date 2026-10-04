"""UserSimEnv exchanges messages, records the conversation and optionally verifies."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import pytest

from agentinstruct import Agent, Runner, Task
from agentinstruct.episode import Message
from agentinstruct.judge import Judgment


@pytest.mark.asyncio
@pytest.mark.parametrize("order", [("user", "assistant"), ("assistant", "user")])
@pytest.mark.parametrize("max_turns", [3, 4])
async def test_agents_take_turns_with_recorded_history(
    tmp_path: Path, order: tuple[Literal["user", "assistant"], ...], max_turns: int
) -> None:
    seen: list[tuple[str, Sequence[Message]]] = []
    client = object()

    class Speaker:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            assert kwargs["client"] is client
            seen.append((kwargs["role"], history))
            return Message("assistant", f"Turn {len(seen)}")

    shared = Agent(generator=Speaker(), instruction="Talk about the topic")
    task = Task(
        agents=dict.fromkeys(order, shared),
        input={"topic": "fractions"},
        max_turns=max_turns,
    )
    await Runner([task], output_dir=tmp_path, client=client).run()
    expected = (list(order) * max_turns)[:max_turns]
    assert [m.role for m in task.episode.messages] == expected
    assert [m.actor_id for m in task.episode.messages] == expected
    for index, (role, history) in enumerate(seen):
        assert role == expected[index]
        assert [m.content for m in history[:2]] == [
            "Talk about the topic",
            '{"topic": "fractions"}',
        ]
        assert list(history[2:]) == task.episode.messages[:index]
    assert not task.episode.verification
    loaded = json.loads((tmp_path / task.episode.id / "trace.json").read_text())
    assert [m["content"] for m in loaded["messages"]] == [
        m.content for m in task.episode.messages
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("dialogue", [False, True])
@pytest.mark.parametrize("verdict", [None, False, True])
async def test_completion_and_optional_verification(
    tmp_path: Path, dialogue: bool, verdict: bool | None
) -> None:
    verified: list[Sequence[Message]] = []

    class Speaker:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            complete = dialogue and kwargs["role"] == "assistant"
            return Message(
                "assistant", "Hello", control="complete" if complete else None
            )

    class Verifier:
        async def evaluate(self, messages: Sequence[Message]) -> Judgment:
            assert not (tmp_path / task.episode.id / "trace.json").exists()
            verified.append(messages)
            return Judgment(bool(verdict))

    agent = Agent(generator=Speaker())
    task = Task(
        agents={"user": agent, "assistant": agent}
        if dialogue
        else {"assistant": agent},
        verifier=Verifier() if verdict is not None else None,
        max_turns=2,
    )
    await Runner([task], output_dir=tmp_path).run()
    assert len(task.episode.messages) == (2 if dialogue else 1)
    assert verified == ([] if verdict is None else [tuple(task.episode.messages)])
    assert (
        task.episode.verification.passed if task.episode.verification else None
    ) is verdict


@pytest.mark.parametrize("max_turns", [0, -1, True, 1.5])
def test_invalid_turn_limits_are_rejected(max_turns: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        Task(agents={"assistant": Agent()}, max_turns=max_turns)
