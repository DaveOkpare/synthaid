"""Task conversation and domain evaluator behavior."""

import json
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Runner, Task, Tool
from agentinstruct.environment import UserSimEnv
from agentinstruct.judge import Judgment
from tests.model_fixtures import Check, Transport, client, response


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.asyncio
async def test_nonfinite_input_fails_before_generation(value: float) -> None:
    task = Task(agents={"assistant": Agent("model")}, input={"value": value})
    with pytest.raises(ValueError, match="Out of range float values"):
        await UserSimEnv().run(task)
    assert not task.episode.messages


@pytest.mark.parametrize(
    "agents",
    [
        {},
        {"user": Agent("model")},
        {"assistant": Agent("model"), "other": Agent("model")},
    ],
)
def test_invalid_participants_are_rejected(agents: Any) -> None:
    with pytest.raises(ValueError):
        Task(agents=agents)


def test_task_records_are_independent_and_construction_is_inert(tmp_path: Path) -> None:
    values: dict[str, Any] = {"topic": ["fractions"]}
    tools: list[Tool] = []
    agent = Agent("model", tools=tools)
    one, two = (
        Task(agents={"assistant": agent}, input=values),
        Task(agents={"assistant": agent}),
    )
    assert one.input["topic"] == ["fractions"]
    assert not two.input
    assert one.episode is not two.episode and one.episode.id != two.episode.id
    assert not list(tmp_path.iterdir())
    with pytest.raises(TypeError):
        Task(agents={"assistant": agent}, tools=[])  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_custom_structural_environment_owns_its_execution(
    tmp_path: Path,
) -> None:
    class Custom:
        async def run(self, task: Task, *, client: Any = None) -> None:
            task.episode.messages.append({"role": "assistant", "content": "custom"})
            if task.verifier is not None:
                task.episode.verification = await task.verifier.evaluate(
                    tuple(task.episode.messages)
                )

    task = Task(
        agents={"assistant": Agent("model")},
        verifier=Check(check=lambda m: True),
    )
    await Runner([task], output_dir=tmp_path, environment=Custom()).run()
    assert task.episode.messages[0]["content"] == "custom"
    assert task.episode.verification is not None and task.episode.verification.passed


@pytest.mark.asyncio
async def test_missing_model_dependency_propagates(tmp_path: Path) -> None:
    task = Task(agents={"assistant": Agent("model")})
    with pytest.raises(ValueError, match="OpenAI client"):
        await Runner([task], output_dir=tmp_path).run()
    assert not task.episode.messages


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["user", "assistant"])
async def test_dialogue_records_roles_and_only_accepted_samples(
    first: Any, tmp_path: Path
) -> None:
    second: Any = "assistant" if first == "user" else "user"
    judge = Check(
        check=lambda m: Judgment('"wrong"' not in json.dumps(m[-1]), "Use correct")
    )
    task = Task(
        agents={
            first: Agent("one"),
            second: Agent("two", reviewer=judge),
        },
        max_turns=3,
        verifier=Check(check=lambda m: len(m) == 3),
    )
    transport = Transport(
        response("question"),
        response("wrong"),
        response("correct"),
        response("thanks"),
    )
    async with client(transport) as borrowed:
        [episode] = await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert episode.messages == [
        {"role": first, "content": "question"},
        {"role": second, "content": "correct"},
        {"role": first, "content": "thanks"},
    ]
    key = "input"
    history = json.loads(transport.requests[-1].content)[key]
    assert history[1]["role"] == "assistant"
    assert "question" in json.dumps(history[1])
    assert history[2] == {"role": "user", "content": "correct"}
    assert episode.path is not None and "wrong" not in episode.path.read_text()
    assert "Use correct" not in json.dumps(history)
    assert "wrong" not in json.dumps(task.agents[first].history)
    assert "wrong" in json.dumps(task.agents[second].history)
    assert "Use correct" in json.dumps(task.agents[second].history)
    assert episode.verification is not None and episode.verification.passed
