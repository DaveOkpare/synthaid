"""Task conversation and callable Judge behavior."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Judge, Runner, Task, Tool
from agentinstruct.environment import UserSimEnv
from agentinstruct.judge import Criterion, Judgment, Rubric
from tests.model_fixtures import Transport, client, response


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.asyncio
async def test_nonfinite_input_fails_before_generation(value: float) -> None:
    task = Task(agents={"assistant": Agent("model")}, input={"value": value})
    with pytest.raises(ValueError, match="Out of range float values"):
        await UserSimEnv().run(task)
    assert not task.episode.messages


@pytest.mark.asyncio
@pytest.mark.parametrize("rubric", [None, Rubric((Criterion("ok"),))])
async def test_callable_judgment_evidence_survives_verification(
    rubric: Rubric | None, tmp_path: Path
) -> None:
    evidence = {"source": "custom-check", "labels": ["stable"]}
    original = Judgment(
        rubric is None,
        "Reviewed",
        {"ok": True} if rubric else {},
        score=0.0,
        evidence=evidence,
    )
    evidence["labels"] = ["changed"]
    judge = Judge(check=lambda messages: original, rubric=rubric)
    evaluated = await judge.evaluate([])
    assert evaluated.passed and evaluated.score == 1.0
    assert evaluated.feedback == "Reviewed"
    assert evaluated.evidence == {"source": "custom-check", "labels": ["stable"]}
    task = Task(agents={"assistant": Agent("model", reviewer=judge)}, verifier=judge)
    async with client(Transport(response())) as borrowed:
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert task.episode.verification == evaluated
    loaded = json.loads((tmp_path / task.episode.id / "trace.json").read_text())
    assert loaded["verification"]["evidence"] == evaluated.evidence


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
        verifier=Judge(check=lambda m: True),
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
async def test_judge_weighted_validation_and_reuse() -> None:
    rubric = Rubric((Criterion("accurate", 3), Criterion("clear", 1)), threshold=0.75)
    judge = Judge(
        check=lambda messages: {
            "criteria": {"accurate": True, "clear": False},
            "feedback": messages[-1]["content"],
        },
        rubric=rubric,
    )
    results = await asyncio.gather(
        *(judge.evaluate([{"role": "assistant", "content": str(i)}]) for i in range(3))
    )
    assert [r.feedback for r in results] == ["0", "1", "2"]
    assert all(r.passed and r.score == 0.75 for r in results)
    with pytest.raises(ValueError):
        Judge(check=lambda messages: True, model="ambiguous")
    for evidence in (
        {"accurate": 1, "clear": True},
        {"accurate": True},
        {"accurate": True, "clear": True, "extra": True},
    ):

        def invalid_check(
            messages: Sequence[Mapping[str, Any]], value: Any = evidence
        ) -> Any:
            return {"criteria": value}

        invalid = Judge(check=invalid_check, rubric=rubric)
        with pytest.raises(RuntimeError):
            await invalid.evaluate([])


def test_overflowing_rubric_is_rejected() -> None:
    with pytest.raises(ValueError):
        Rubric((Criterion("one", 1e308), Criterion("two", 1e308)))


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["user", "assistant"])
async def test_dialogue_records_roles_and_only_accepted_samples(
    first: Any, tmp_path: Path
) -> None:
    second: Any = "assistant" if first == "user" else "user"
    judge = Judge(
        check=lambda m: Judgment('"wrong"' not in json.dumps(m[-1]), "Use correct")
    )
    task = Task(
        agents={
            first: Agent("one"),
            second: Agent("two", reviewer=judge),
        },
        max_turns=3,
        verifier=Judge(check=lambda m: len(m) == 3),
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
