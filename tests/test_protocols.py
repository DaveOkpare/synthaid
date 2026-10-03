"""Domain adapters cross small structural seams without framework inheritance."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from agentinstruct import Agent, Environment, Episode, Runner, Task, Tool
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
    ) -> tuple[Message, ...]:
        operands = json.loads(history[1].content)["operands"]
        content = json.dumps({"operands": operands, "sum": sum(operands)})
        return (Message("assistant", content, control="complete"),)


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
    assert all(result.status == "accepted" for result in results)
    assert [json.loads(e.messages[0].content)["sum"] for e in results] == [3, 12]
    assert all(e.verification[0]["events"] == {"domain": "arithmetic"} for e in results)
    assert all(Episode.load(tmp_path / e.id).status == "accepted" for e in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "failure", "timeout"])
async def test_standalone_environment_owns_recording_and_deadline(
    tmp_path: Path, mode: str
) -> None:
    class DomainGenerator:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            if mode == "failure":
                raise ValueError("Domain failure")
            if mode == "timeout":
                await asyncio.Event().wait()
            return (await Arithmetic().generate(history))[0]

    environment: Environment = UserSimEnv()
    task = Task(
        agents={"assistant": Agent(generator=DomainGenerator())},
        input={"mode": mode, "operands": [2, 3]},
        timeout_seconds=0.01,
        verifier=ArithmeticCheck(),
    )
    task.episode.open(tmp_path / task.episode.id)
    await environment.run(task)
    assert task.episode.sealed
    assert (
        task.episode.status
        == {
            "success": "accepted",
            "failure": "failed",
            "timeout": "unverified",
        }[mode]
    )
    if mode == "timeout":
        # The verifier cannot score an empty conversation; it records an error.
        assert task.episode.generation == {"state": "truncated", "reason": "timeout"}
        assert task.episode.status == "unverified"


@pytest.mark.asyncio
async def test_runner_only_opens_invokes_and_collects_episodes(tmp_path: Path) -> None:
    calls: list[tuple[Task, Any]] = []
    client = object()

    class Custom:
        async def run(self, task: Task, *, client: Any = None) -> None:
            assert task.episode.path == tmp_path / task.episode.id
            assert not task.episode.metadata and not task.episode.events
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
    assert not task.episode.sealed and not task.episode.verification


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
    assert not task.episode.sealed and not task.episode.events
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
    await Runner([task], output_dir=tmp_path).run()
    assert not effects
    assert task.episode.status == ("failed" if placement == "review" else "unverified")
    if placement == "verification":
        assert task.episode.verification[-1]["error"]["exception"] == "ValueError"


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.1])
def test_judgment_score_cannot_bypass_the_local_contract(score: float) -> None:
    with pytest.raises(ValueError, match="score"):
        Judgment(True, score=score)


def test_protocol_construction_rejects_missing_operations() -> None:
    invalid: Any = object()
    with pytest.raises(ValueError, match="generate"):
        Agent(generator=invalid)
    with pytest.raises(ValueError, match="evaluate"):
        Task(agents={"assistant": Agent()}, verifier=invalid)
    with pytest.raises(ValueError, match="evaluate"):
        Agent(reviewer=invalid)


@pytest.mark.asyncio
async def test_domain_evaluator_io_error_is_recorded_without_aborting_batch(
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
    results = await Runner(tasks, output_dir=tmp_path).run()
    assert [episode.status for episode in results] == ["unverified", "accepted"]
    assert results[0].verification[-1]["error"]["exception"] == "OSError"
