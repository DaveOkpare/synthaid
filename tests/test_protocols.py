"""Domain adapters cross small structural seams without framework inheritance."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agentinstruct import Agent, Environment, Runner, Task, Tool
from agentinstruct.environment import UserSimEnv
from agentinstruct.judge import Evaluator, Judgment
from tests.model_fixtures import Transport, client, response


class ArithmeticCheck:
    async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
        content = messages[-1]["content"]
        result = json.loads(content if isinstance(content, str) else content[0]["text"])
        passed = sum(result["operands"]) == result["sum"]
        return Judgment(passed, evidence={"domain": "arithmetic"})


@pytest.mark.asyncio
async def test_plain_domain_evaluator_is_reusable(
    tmp_path: Path,
) -> None:
    evaluator: Evaluator = ArithmeticCheck()
    agent = Agent("model", reviewer=evaluator)
    tasks = [
        Task(
            agents={"assistant": agent}, input={"operands": values}, verifier=evaluator
        )
        for values in ([1, 2], [7, 5])
    ]
    transport = Transport(
        *(
            response(json.dumps({"operands": values, "sum": sum(values)}))
            for values in ([1, 2], [7, 5])
        )
    )
    async with client(transport) as borrowed:
        results = await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
    assert all(
        result.verification is not None and result.verification.passed
        for result in results
    )
    assert [json.loads(e.messages[0]["content"])["sum"] for e in results] == [3, 12]
    assert all(
        e.verification is not None
        and e.verification.evidence == {"domain": "arithmetic"}
        for e in results
    )
    assert all(
        json.loads((tmp_path / e.id / "trace.json").read_text())["verification"][
            "passed"
        ]
        for e in results
    )


@pytest.mark.asyncio
async def test_standalone_usersim_inherits_environment_and_records(
    tmp_path: Path,
) -> None:
    environment: Environment = UserSimEnv()
    task = Task(
        agents={"assistant": Agent("model")},
        input={"operands": [2, 3]},
        verifier=ArithmeticCheck(),
    )
    task.episode.path = tmp_path / task.episode.id / "trace.json"
    async with client(Transport(response('{"operands":[2,3],"sum":5}'))) as borrowed:
        await environment.run(task, client=borrowed)
    assert task.episode.verification is not None and task.episode.verification.passed
    assert json.loads(task.episode.messages[0]["content"])["sum"] == 5
    assert not task.episode.path.exists()


@pytest.mark.asyncio
async def test_runner_invokes_saves_and_collects_episodes(tmp_path: Path) -> None:
    calls: list[tuple[Task, Any]] = []
    client = object()

    class Custom:
        async def run(self, task: Task, *, client: Any = None) -> None:
            assert task.episode.path == tmp_path / task.episode.id / "trace.json"
            assert not task.episode.metadata and not task.episode.messages
            calls.append((task, client))
            await asyncio.sleep(0.02)

    task = Task(
        agents={"assistant": Agent("model")},
        verifier=ArithmeticCheck(),
    )
    other = Task(agents={"assistant": Agent("model")})
    results = await Runner(
        [task, other], output_dir=tmp_path, client=client, environment=Custom()
    ).run()
    assert calls == [(task, client), (other, client)]
    assert results[0] is task.episode and results[1] is other.episode
    assert task.episode.verification is None
    assert all(
        episode.path is not None and episode.path.is_file() for episode in results
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
async def test_runner_propagates_environment_errors_without_finalizing(
    tmp_path: Path, failure: type[BaseException]
) -> None:
    error = failure("Domain failure")

    class Custom:
        async def run(self, task: Task, *, client: Any = None) -> None:
            raise error

    task, other = (Task(agents={"assistant": Agent("model")}) for _ in range(2))
    with pytest.raises(failure) as raised:
        await Runner([task, other], output_dir=tmp_path, environment=Custom()).run()
    assert raised.value is error
    assert not task.episode.messages
    assert other.episode.path is None


@pytest.mark.asyncio
@pytest.mark.parametrize("placement", ["review", "verification"])
async def test_malformed_domain_evaluation_never_authorizes_effects(
    tmp_path: Path, placement: str
) -> None:
    effects: list[str] = []

    async def effect(arguments: Mapping[str, Any]) -> Any:
        effects.append("effect")
        return {}

    class Malformed:
        async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
            result: Any = SimpleNamespace(
                passed="yes", criteria={}, feedback="", score=1.0, evidence={}
            )
            return cast(Judgment, result)

    evaluator = Malformed()
    agent = Agent(
        model="model",
        tools=[Tool(effect)],
        reviewer=evaluator if placement == "review" else None,
    )
    task = Task(
        agents={"assistant": agent},
        verifier=evaluator if placement == "verification" else None,
    )
    async with client(Transport(response())) as borrowed:
        with pytest.raises(ValueError, match="Judgment"):
            await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert not effects
    assert bool(task.episode.messages) == (placement == "verification")
    assert task.episode.verification is None


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.1])
def test_judgment_score_cannot_bypass_the_local_contract(score: float) -> None:
    with pytest.raises(ValueError, match="score"):
        Judgment(True, score=score)


@pytest.mark.asyncio
async def test_domain_evaluator_io_error_propagates(
    tmp_path: Path,
) -> None:
    class DomainCheck:
        async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
            if json.loads(messages[-1]["content"])["sum"] == 3:
                raise OSError("Domain data unavailable")
            return Judgment(True)

    tasks = [
        Task(
            agents={"assistant": Agent("model")},
            input={"operands": values},
            verifier=DomainCheck(),
        )
        for values in ([1, 2], [7, 5])
    ]
    async with client(Transport(response('{"operands":[1,2],"sum":3}'))) as borrowed:
        with pytest.raises(OSError, match="Domain data unavailable"):
            await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
    assert tasks[0].episode.verification is None
    assert tasks[0].episode.path is not None and tasks[0].episode.path.is_file()
    assert tasks[1].episode.path is None
