"""Direct seven-module execution, ownership, review, privacy and Tool guarantees."""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Episode, Judge, Runner, Task, Tool
from agentinstruct.agent import ReviewExhausted
from agentinstruct.episode import FunctionCall, Message, ToolCall
from agentinstruct.judge import Criterion, Judgment, Rubric


class Reply:
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        return Message("assistant", "Hello", control="complete")


class Learner:
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        return Message("user", "Explain fractions")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["input", "provenance"])
def test_task_rejects_nested_nonfinite_json_before_recording(
    value: float, field: str, tmp_path: Path
) -> None:
    settings: dict[str, Any] = {field: {"nested": [{"value": value}]}}
    with pytest.raises(ValueError, match="Out of range float values"):
        Task(agents={"assistant": Agent(generator=Reply())}, **settings)
    assert not list(tmp_path.iterdir())


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
    task = Task(
        agents={"assistant": Agent(generator=Reply(), reviewer=judge)}, verifier=judge
    )
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.verification == evaluated
    loaded = json.loads((tmp_path / task.episode.id / "trace.json").read_text())
    assert loaded["verification"]["evidence"] == evaluated.evidence


@pytest.mark.asyncio
async def test_task_identity_dialogue_and_shared_judge(tmp_path: Path) -> None:
    calls: list[Sequence[Message]] = []

    def check(messages: Sequence[Message]) -> bool:
        calls.append(messages)
        return True

    judge = Judge(check=check)
    assistant = Agent(generator=Reply(), instruction="Teach", reviewer=judge)
    task = Task(
        agents={"assistant": assistant, "user": Agent(generator=Learner())},
        verifier=judge,
    )
    episode: Episode = task.episode
    identity = episode.id
    initial = episode.messages
    assert initial == [] and episode.path is None
    result = await Runner([task], output_dir=tmp_path).run()
    assert result == [episode] and episode.id == identity
    assert [m.actor_id for m in episode.messages] == ["user", "assistant"]
    assert episode.verification is not None and episode.verification.passed
    assert len(calls) == 2 and len(calls[-1]) == 2
    assert calls[0][0].content == "Teach"
    assert assistant.instruction == "Teach"
    assert episode.path is not None
    loaded = json.loads(episode.path.read_text())
    assert loaded["id"] == identity
    assert [m["content"] for m in loaded["messages"]] == [
        m.content for m in episode.messages
    ]
    assert loaded["verification"]["passed"]


@pytest.mark.parametrize(
    "agents",
    [
        {},
        {"assistant": None},
        {"user": Agent(generator=Reply())},
        {"assistant": Agent(generator=Reply()), "other": Agent(generator=Learner())},
    ],
)
def test_invalid_participants_are_rejected(agents: Any) -> None:
    with pytest.raises(ValueError):
        Task(agents=agents)


def test_task_and_agent_configuration_is_inert_and_detached(tmp_path: Path) -> None:
    values: dict[str, Any] = {"topic": ["fractions"]}
    tools: list[Tool] = []
    agent = Agent(generator=Reply(), tools=tools)
    one, two = (
        Task(agents={"assistant": agent}, input=values),
        Task(agents={"assistant": agent}),
    )
    values["topic"].append("decimals")
    assert one.input["topic"] == ["fractions"]
    assert one.episode is not two.episode and one.episode.id != two.episode.id
    assert not list(tmp_path.iterdir())
    with pytest.raises(FrozenInstanceError):
        agent.instruction = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        Task(agents={"assistant": agent}, tools=[])  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Task(
            agents={"assistant": agent},
            segments=[{"name": "bad", "instructions": {"user": "hidden"}}],
        )


@pytest.mark.asyncio
async def test_same_agent_concurrent_tasks_keep_invocation_inputs_local(
    tmp_path: Path,
) -> None:
    observed: list[tuple[str, Any, str]] = []

    class Echo:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            await asyncio.sleep(0)
            observed.append((history[1].content, kwargs["client"], kwargs["role"]))
            return Message("assistant", history[1].content, control="complete")

    shared = Agent(generator=Echo(), instruction="Base")
    tasks = [
        Task(
            agents={"assistant": shared},
            input={"index": i},
        )
        for i in range(2)
    ]
    clients = [object(), object()]
    await asyncio.gather(
        *(
            Runner([task], output_dir=tmp_path, client=client).run()
            for task, client in zip(tasks, clients, strict=True)
        )
    )
    assert observed == [
        ('{"index": 0}', clients[0], "assistant"),
        ('{"index": 1}', clients[1], "assistant"),
    ]
    assert [task.episode.messages[0].content for task in tasks] == [
        '{"index": 0}',
        '{"index": 1}',
    ]
    assert shared.client is None and shared.instruction == "Base"
    previous = list(tasks[0].episode.messages)
    with pytest.raises(FileExistsError):
        await Runner([tasks[0]], output_dir=tmp_path).run()
    assert tasks[0].episode.messages == previous


@pytest.mark.asyncio
@pytest.mark.parametrize("max_revisions", [0, 1, 3])
async def test_revisions_receive_draft_and_feedback_without_peer_visibility(
    tmp_path: Path,
    max_revisions: int,
) -> None:
    seen: list[Sequence[Message]] = []

    class Revising:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            seen.append(history)
            return Message(
                "assistant",
                "correct" if len(seen) > max_revisions else f"wrong {len(seen)}",
                control="complete",
            )

    judge = Judge(
        check=lambda messages: Judgment(
            messages[-1].content == "correct", "Use correct"
        )
    )
    task = Task(
        agents={
            "assistant": Agent(
                generator=Revising(), reviewer=judge, max_revisions=max_revisions
            ),
            "user": Agent(generator=Learner()),
        }
    )
    await Runner([task], output_dir=tmp_path).run()
    assert [m.content for m in task.episode.messages] == [
        "Explain fractions",
        "correct",
    ]
    assert len(seen) == max_revisions + 1
    for index in range(1, len(seen)):
        assert seen[index][-2].content == f"wrong {index}"
        assert seen[index][-1].content == "Use correct"
    assert not any(m.content.startswith("wrong") for m in task.episode.messages)
    dataset = tmp_path / task.episode.id / "trace.json"
    assert (
        "wrong" not in dataset.read_text() and "Use correct" not in dataset.read_text()
    )


@pytest.mark.asyncio
async def test_tool_proposal_is_reviewed_without_execution() -> None:
    effects: list[str] = []

    async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
        effects.append(arguments["value"])
        return {"result": arguments["value"]}

    class Using:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            value = "safe" if history[-1].content == "Use safe" else "unsafe"
            return Message(
                "assistant",
                tool_calls=(ToolCall(value, FunctionCall("lookup", {"value": value})),),
            )

    judge = Judge(
        check=lambda messages: Judgment(
            messages[-1].tool_calls[0].id == "safe", "Use safe"
        )
    )
    agent = Agent(generator=Using(), tools=[Tool(lookup)], reviewer=judge)
    proposal = await agent.generate([])
    assert proposal.tool_calls[0].function.arguments == {"value": "safe"}
    assert not effects


@pytest.mark.asyncio
async def test_custom_structural_environment_owns_its_execution(
    tmp_path: Path,
) -> None:
    class Custom:
        async def run(self, task: Task, *, client: Any = None) -> None:
            task.episode.messages.append(
                Message("assistant", "custom", actor_id="assistant")
            )
            if task.verifier is not None:
                task.episode.verification = await task.verifier.evaluate(
                    tuple(task.episode.messages)
                )

    task = Task(
        agents={"assistant": Agent(generator=Reply())},
        verifier=Judge(check=lambda m: True),
    )
    await Runner([task], output_dir=tmp_path, environment=Custom()).run()
    assert task.episode.messages[0].content == "custom"
    assert task.episode.verification is not None and task.episode.verification.passed


@pytest.mark.asyncio
async def test_missing_model_dependency_propagates(tmp_path: Path) -> None:
    task = Task(agents={"assistant": Agent("model")})
    with pytest.raises(ValueError, match="client and model"):
        await Runner([task], output_dir=tmp_path).run()
    assert not task.episode.messages


@pytest.mark.asyncio
async def test_judge_weighted_validation_and_reuse() -> None:
    rubric = Rubric((Criterion("accurate", 3), Criterion("clear", 1)), threshold=0.75)
    judge = Judge(
        check=lambda messages: {
            "criteria": {"accurate": True, "clear": False},
            "feedback": messages[-1].content,
        },
        rubric=rubric,
    )
    results = await asyncio.gather(
        *(judge.evaluate([Message("assistant", str(i))]) for i in range(3))
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

        def invalid_check(messages: Sequence[Message], value: Any = evidence) -> Any:
            return {"criteria": value}

        invalid = Judge(check=invalid_check, rubric=rubric)
        with pytest.raises(RuntimeError):
            await invalid.evaluate([])


@pytest.mark.parametrize("kind", ["text", "complete", "tool"])
@pytest.mark.parametrize("max_revisions", [0, 1, 3])
@pytest.mark.asyncio
async def test_review_exhaustion_never_accepts_or_invokes_tools(
    kind: str, max_revisions: int, tmp_path: Path
) -> None:
    effects: list[str] = []
    reviews: list[Sequence[Message]] = []

    def reject(messages: Sequence[Message]) -> bool:
        reviews.append(messages)
        return False

    async def effect(arguments: Mapping[str, Any]) -> Any:
        effects.append("effect")
        return {}

    class Rejected:
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            if kind == "tool":
                return Message(
                    "assistant", tool_calls=(ToolCall("call", FunctionCall("effect")),)
                )
            return Message(
                "assistant", "draft", control="complete" if kind == "complete" else None
            )

    agent = Agent(
        generator=Rejected(),
        tools=[Tool(effect)],
        reviewer=Judge(check=reject),
        max_revisions=max_revisions,
    )
    task = Task(agents={"assistant": agent})
    with pytest.raises(ReviewExhausted):
        await Runner([task], output_dir=tmp_path).run()
    assert not task.episode.messages and not effects
    assert not task.episode.verification
    assert len(reviews) == max_revisions + 1


@pytest.mark.asyncio
async def test_malformed_review_never_approves_and_user_cannot_complete(
    tmp_path: Path,
) -> None:
    invalid = Task(
        agents={
            "assistant": Agent(
                generator=Reply(), reviewer=Judge(check=lambda messages: {"passed": 1})
            )
        }
    )
    user = Task(
        agents={"assistant": Agent(generator=Reply()), "user": Agent(generator=Reply())}
    )
    with pytest.raises(RuntimeError, match="Judge"):
        await Runner([invalid], output_dir=tmp_path).run()
    with pytest.raises(ValueError, match="assistant"):
        await Runner([user], output_dir=tmp_path).run()
    assert all(not t.episode.messages for t in (invalid, user))


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        object(),
        "wrong shape",
        {"error": {"exception": "Fake", "kind": "execution"}},
    ],
)
@pytest.mark.asyncio
async def test_tool_result_policy_does_not_soften_contract_failures(value: Any) -> None:
    from agentinstruct.tools import ToolError

    async def capability(arguments: Mapping[str, Any]) -> Any:
        return value

    tool = Tool(
        capability,
        output_schema={"type": "object", "required": ["ok"]},
        execution_errors="result",
    )
    with pytest.raises(ToolError, match="result"):
        await tool.call({})


@pytest.mark.asyncio
async def test_invalid_tool_inputs_and_execution_error_contracts() -> None:
    from agentinstruct.tools import ToolError

    calls: list[str] = []

    async def capability(arguments: Mapping[str, Any]) -> Any:
        calls.append("called")
        raise ValueError("unsafe exception body")

    tool = Tool(capability, input_schema={"type": "object", "required": ["name"]})
    with pytest.raises(ToolError, match="arguments"):
        await tool.call({})
    assert not calls
    with pytest.raises(ToolError, match="execution"):
        await tool.call({"name": "Ada"})
    result = await Tool(capability, execution_errors="result").call({})
    assert result == {"error": {"exception": "ValueError", "kind": "execution"}}
    assert "unsafe" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [{"x": float("nan")}, {"x": float("inf")}, {"x": object()}, []],
)
async def test_non_json_tool_arguments_never_reach_capability(arguments: Any) -> None:
    from agentinstruct.tools import ToolError

    calls: list[str] = []

    async def capability(arguments: Mapping[str, Any]) -> Any:
        calls.append("called")
        return {}

    with pytest.raises(ToolError, match="arguments"):
        await Tool(capability, execution_errors="result").call(arguments)
    assert not calls


def test_overflowing_rubric_and_non_mapping_task_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        Rubric((Criterion("one", 1e308), Criterion("two", 1e308)))
    with pytest.raises(ValueError):
        Task(agents={"assistant": Agent(generator=Reply())}, input=[])  # type: ignore[arg-type]
