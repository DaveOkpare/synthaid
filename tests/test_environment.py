"""UserSimEnv exchanges messages, records the conversation and optionally verifies."""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Runner, Task
from agentinstruct.environment import UserSimEnv
from agentinstruct.episode import Message
from agentinstruct.judge import Judgment


@pytest.mark.asyncio
@pytest.mark.parametrize("initiator", ["user", "assistant"])
@pytest.mark.parametrize("max_rounds,max_turns,turns", [(2, 100, 4), (10, 3, 3)])
async def test_agents_take_turns_with_recorded_history(
    tmp_path: Path, initiator: str, max_rounds: int, max_turns: int, turns: int
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
        agents={"assistant": shared, "user": shared},
        input={"topic": "fractions"},
        initiator=initiator,
        max_rounds=max_rounds,
        max_turns=max_turns,
    )
    await Runner([task], output_dir=tmp_path, client=client).run()
    expected = list(task.roles) * max_rounds
    assert [m.role for m in task.episode.messages] == expected[:turns]
    assert [m.actor_id for m in task.episode.messages] == expected[:turns]
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
        agents={"assistant": agent, "user": agent}
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [
        {"segments": [{"name": "draft"}]},
        {"timeout_seconds": 1.0},
    ],
)
async def test_unsupported_settings_fail_before_generation(
    tmp_path: Path, settings: dict[str, Any]
) -> None:
    task = Task(agents={"assistant": Agent()}, **settings)
    task.episode.path = tmp_path / task.episode.id / "trace.json"
    with pytest.raises(ValueError, match="does not support segments or deadlines"):
        await UserSimEnv().run(task)
    assert not task.episode.messages and not task.episode.path.exists()
