"""Domain adapters cross small structural seams without framework inheritance."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agentinstruct import Agent, Environment, Runner, Task, Tool
from agentinstruct.agent import Generator
from agentinstruct.environment import UserSimEnv
from agentinstruct.episode import FunctionCall, Message, ToolCall
from agentinstruct.judge import Evaluator, Judgment


class Arithmetic:
    async def generate(
        self,
        history: Sequence[Message],
        *,
        client: Any = None,
        role: str = "assistant",
        instruction: str | None = None,
    ) -> Message:
        operands = json.loads(history[1].content)["operands"]
        content = json.dumps({"operands": operands, "sum": sum(operands)})
        return Message("assistant", content, control="complete")


class ArithmeticCheck:
    async def evaluate(self, messages: Sequence[Message]) -> Judgment:
        result = json.loads(messages[-1].content)
        passed = sum(result["operands"]) == result["sum"]
        return Judgment(passed, evidence={"domain": "arithmetic"})


@pytest.mark.asyncio
async def test_plain_domain_generator_and_evaluator_are_reusable(
    tmp_path: Path,
) -> None:
    generator: Generator = Arithmetic()
    evaluator: Evaluator = ArithmeticCheck()
    agent = Agent(generator=generator, reviewer=evaluator)
    tasks = [
        Task(
            agents={"assistant": agent}, input={"operands": values}, verifier=evaluator
        )
        for values in ([1, 2], [7, 5])
    ]
    results = await Runner(tasks, output_dir=tmp_path, client=object()).run()
    assert all(
        result.verification is not None and result.verification.passed
        for result in results
    )
    assert [json.loads(e.messages[0].content)["sum"] for e in results] == [3, 12]
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
        agents={"assistant": Agent(generator=Arithmetic())},
        input={"operands": [2, 3]},
        verifier=ArithmeticCheck(),
    )
    task.episode.path = tmp_path / task.episode.id / "trace.json"
    await environment.run(task)
    assert task.episode.verification is not None and task.episode.verification.passed
    assert json.loads(task.episode.messages[0].content)["sum"] == 5
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
        agents={"assistant": Agent()},
        timeout_seconds=0.001,
        verifier=ArithmeticCheck(),
    )
    other = Task(agents={"assistant": Agent()})
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

    task, other = (Task(agents={"assistant": Agent()}) for _ in range(2))
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

    class Proposal:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            if placement == "verification":
                return Message("assistant", "plain", control="complete")
            return Message(
                "assistant", tool_calls=(ToolCall("id", FunctionCall("effect")),)
            )

    class Malformed:
        async def evaluate(self, messages: Sequence[Message]) -> Judgment:
            result: Any = SimpleNamespace(
                passed="yes", criteria={}, feedback="", score=1.0, evidence={}
            )
            return cast(Judgment, result)

    evaluator = Malformed()
    agent = Agent(
        generator=Proposal(),
        tools=[Tool(effect)],
        reviewer=evaluator if placement == "review" else None,
    )
    task = Task(
        agents={"assistant": agent},
        verifier=evaluator if placement == "verification" else None,
    )
    with pytest.raises(ValueError, match="Judgment"):
        await Runner([task], output_dir=tmp_path).run()
    assert not effects
    assert bool(task.episode.messages) == (placement == "verification")
    assert task.episode.verification is None


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.1])
def test_judgment_score_cannot_bypass_the_local_contract(score: float) -> None:
    with pytest.raises(ValueError, match="score"):
        Judgment(True, score=score)


def test_task_verifier_requires_an_evaluator() -> None:
    invalid: Any = object()
    with pytest.raises(ValueError, match="evaluate"):
        Task(agents={"assistant": Agent()}, verifier=invalid)


@pytest.mark.asyncio
async def test_domain_evaluator_io_error_propagates(
    tmp_path: Path,
) -> None:
    class DomainCheck:
        async def evaluate(self, messages: Sequence[Message]) -> Judgment:
            if json.loads(messages[-1].content)["sum"] == 3:
                raise OSError("Domain data unavailable")
            return Judgment(True)

    tasks = [
        Task(
            agents={"assistant": Agent(generator=Arithmetic())},
            input={"operands": values},
            verifier=DomainCheck(),
        )
        for values in ([1, 2], [7, 5])
    ]
    with pytest.raises(OSError, match="Domain data unavailable"):
        await Runner(tasks, output_dir=tmp_path).run()
    assert tasks[0].episode.verification is None
    assert tasks[0].episode.path is not None and tasks[0].episode.path.is_file()
    assert tasks[1].episode.path is None
