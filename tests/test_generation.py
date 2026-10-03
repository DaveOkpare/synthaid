"""Direct seven-module execution, ownership, review, privacy and Tool guarantees."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Agent, Episode, Judge, Runner, Task, Tool
from agentinstruct.episode import FunctionCall, Message, ToolCall
from agentinstruct.judge import Criterion, Judgment, Rubric


class Reply(Agent):
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        return Message("assistant", "Hello", control="complete")


class Learner(Agent):
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        return Message("user", "Explain fractions")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("field", ["input", "provenance"])
def test_task_rejects_nested_nonfinite_json_before_recording(
    value: float, field: str, tmp_path: Path
) -> None:
    settings: dict[str, Any] = {field: {"nested": [{"value": value}]}}
    with pytest.raises(ValueError, match="JSON numbers must be finite"):
        Task(agents={"assistant": Reply()}, **settings)
    assert not list(tmp_path.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("rubric", [None, Rubric((Criterion("ok"),))])
async def test_callable_judgment_evidence_survives_review_and_verification(
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
    assert evaluated.evidence == {"source": "custom-check", "labels": ("stable",)}
    task = Task(agents={"assistant": Reply(reviewer=judge)}, verifier=judge)
    await Runner([task], output_dir=tmp_path).run()
    review = next(e for e in task.episode.events if e["kind"] == "review_result")
    assert review["data"]["model_call"] == evaluated.evidence
    assert task.episode.verification[0]["events"] == evaluated.evidence
    assert task.episode.status == "accepted" and not task.episode.messages[0].evidence
    loaded = Episode.load(tmp_path / task.episode.id)
    assert loaded.verification[0]["events"] == evaluated.evidence


@pytest.mark.asyncio
async def test_task_identity_segments_and_shared_judge(tmp_path: Path) -> None:
    calls: list[Sequence[Message]] = []

    def check(messages: Sequence[Message]) -> bool:
        calls.append(messages)
        return True

    judge = Judge(check=check)
    assistant = Reply(instruction="Teach", reviewer=judge)
    task = Task(
        agents={"assistant": assistant, "user": Learner()},
        verifier=judge,
        segments=[
            {"name": "draft", "instructions": {"assistant": "Draft"}},
            {"name": "revise", "instructions": {"assistant": "Revise"}},
        ],
    )
    episode: Episode = task.episode
    identity = episode.id
    initial = episode.messages
    assert initial == () and episode.path is None
    result = await Runner([task], output_dir=tmp_path).run()
    assert result == [episode] and episode.id == identity and episode.sealed
    assert [m.actor_id for m in episode.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert [m.segment for m in episode.messages] == [
        "draft",
        "draft",
        "revise",
        "revise",
    ]
    assert episode.status == "accepted" and len(episode.verification) == 1
    assert len(calls) == 3 and len(calls[-1]) == 4
    assert calls[0][0].content == "Teach\n\nDraft"
    assert calls[1][0].content == "Teach\n\nRevise"
    assert assistant.instruction == "Teach"
    loaded = Episode.load(episode.path or tmp_path)
    assert loaded.id == identity and loaded.messages == episode.messages
    assert loaded.status == "accepted"


@pytest.mark.parametrize(
    "agents",
    [
        {},
        {"assistant": None},
        {"user": Reply()},
        {"assistant": Reply(), "other": Learner()},
    ],
)
def test_invalid_participants_are_rejected(agents: Any) -> None:
    with pytest.raises(ValueError):
        Task(agents=agents)


def test_task_and_agent_configuration_is_inert_and_detached(tmp_path: Path) -> None:
    values: dict[str, Any] = {"topic": ["fractions"]}
    tools: list[Tool] = []
    agent = Reply(tools=tools)
    one, two = (
        Task(agents={"assistant": agent}, input=values),
        Task(agents={"assistant": agent}),
    )
    values["topic"].append("decimals")
    assert one.input["topic"] == ("fractions",)
    assert one.episode is not two.episode and one.episode.id != two.episode.id
    assert not list(tmp_path.iterdir())
    with pytest.raises(FrozenInstanceError):
        agent.instruction = "mutated"  # type: ignore[misc]
    with pytest.raises(TypeError):
        Task(agents={"assistant": agent}, tools=[])  # type: ignore[call-arg]
    with pytest.raises(AttributeError):
        one.episode.id = "replacement"  # type: ignore[misc]
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

    class Echo(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            await asyncio.sleep(0)
            observed.append((history[0].content, kwargs["client"], kwargs["role"]))
            return Message("assistant", history[0].content, control="complete")

    shared = Echo(instruction="Base")
    tasks = [
        Task(
            agents={"assistant": shared},
            segments=[{"name": str(i), "instructions": {"assistant": str(i)}}],
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
        ("Base\n\n0", clients[0], "assistant"),
        ("Base\n\n1", clients[1], "assistant"),
    ]
    assert [task.episode.messages[0].content for task in tasks] == [
        "Base\n\n0",
        "Base\n\n1",
    ]
    assert shared.client is None and shared.instruction == "Base"
    previous = tasks[0].episode.to_dict()
    with pytest.raises(RuntimeError):
        await Runner([tasks[0]], output_dir=tmp_path).run()
    assert tasks[0].episode.to_dict() == previous


@pytest.mark.asyncio
async def test_revisions_receive_draft_and_feedback_without_peer_visibility(
    tmp_path: Path,
) -> None:
    seen: list[Sequence[Message]] = []

    class Revising(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            seen.append(history)
            return Message(
                "assistant",
                "correct" if "Use correct" in history[-1].content else "wrong",
                control="complete",
            )

    judge = Judge(
        check=lambda messages: Judgment(
            messages[-1].content == "correct", "Use correct"
        )
    )
    task = Task(agents={"assistant": Revising(reviewer=judge), "user": Learner()})
    await Runner([task], output_dir=tmp_path).run()
    assert [m.content for m in task.episode.messages] == [
        "Explain fractions",
        "correct",
    ]
    assert seen[1][-2].content == "wrong" and "Use correct" in seen[1][-1].content
    assert len([e for e in task.episode.events if e["kind"] == "review_result"]) == 2
    assert not any(m.content == "wrong" for m in task.episode.history("user"))
    dataset = tmp_path / "dataset.jsonl"
    task.episode.export(dataset)
    assert (
        "wrong" not in dataset.read_text() and "Use correct" not in dataset.read_text()
    )


@pytest.mark.asyncio
async def test_rejected_tool_is_revised_before_any_effect(tmp_path: Path) -> None:
    effects: list[str] = []

    async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
        effects.append(arguments["value"])
        return {"result": arguments["value"]}

    tool = Tool(lookup)

    class Using(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            if history[-1].role == "tool":
                return Message("assistant", "done", control="complete")
            value = "safe" if "Use safe" in history[-1].content else "unsafe"
            return Message(
                "assistant",
                tool_calls=(ToolCall(value, FunctionCall("lookup", {"value": value})),),
            )

    judge = Judge(
        check=lambda messages: Judgment(
            not messages[-1].tool_calls or messages[-1].tool_calls[0].id == "safe",
            "Use safe",
        )
    )
    task = Task(agents={"assistant": Using(tools=[tool], reviewer=judge)})
    await Runner([task], output_dir=tmp_path).run()
    assert effects == ["safe"]
    assert [m.role for m in task.episode.messages] == ["assistant", "tool", "assistant"]
    assert [m.content for m in task.episode.history("user")] == ["done"]
    assert task.episode.training_messages() == [
        {"role": "assistant", "content": "done"}
    ]


@pytest.mark.asyncio
async def test_tools_are_agent_local_and_intent_is_durable(tmp_path: Path) -> None:
    async def effect(arguments: Mapping[str, Any]) -> dict[str, Any]:
        assert task.episode.path is not None
        assert '"tool_calls"' in (task.episode.path / "conversation.jsonl").read_text()
        return {"ok": True}

    class UserTool(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            return Message(
                "assistant", tool_calls=(ToolCall("call", FunctionCall("effect")),)
            )

    task = Task(agents={"assistant": Reply(tools=[Tool(effect)]), "user": UserTool()})
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.status == "failed" and task.episode.messages == ()


@pytest.mark.asyncio
async def test_custom_structural_environment_uses_common_recording_and_failures(
    tmp_path: Path,
) -> None:
    class Custom:
        async def run(self, task: Task, *, client: Any = None) -> None:
            task.episode.append(Message("assistant", "custom", actor_id="assistant"))

    class Unusable:
        async def run(self, task: Task, *, client: Any = None) -> None:
            raise ValueError("Domain execution failed")

    task = Task(agents={"assistant": Reply()}, verifier=Judge(check=lambda m: True))
    await Runner([task], output_dir=tmp_path, environment=Custom()).run()
    assert task.episode.messages[0].content == "custom"
    assert task.episode.sealed and task.episode.status == "accepted"
    missing = Task(agents={"assistant": Reply()})
    await Runner([missing], output_dir=tmp_path, environment=Unusable()).run()
    assert missing.episode.sealed and missing.episode.status == "failed"


@pytest.mark.asyncio
async def test_missing_model_dependency_is_recorded_by_agent(tmp_path: Path) -> None:
    task = Task(agents={"assistant": Agent("model")})
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.sealed and task.episode.status == "failed"
    assert any(event["kind"] == "agent_generate_error" for event in task.episode.events)


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


@pytest.mark.asyncio
async def test_each_message_gets_its_own_revision_budget(tmp_path: Path) -> None:
    observations: list[Sequence[Message]] = []

    class Batch(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Any:
            observations.append(history)
            if history[-1].content.startswith("Private review feedback:"):
                return Message("assistant", history[-2].content.replace("bad", "good"))
            return [
                Message("assistant", "first bad"),
                Message("assistant", "second bad"),
            ]

    judge = Judge(
        check=lambda messages: Judgment(
            "good" in messages[-1].content, "Replace bad with good"
        )
    )
    task = Task(agents={"assistant": Batch(reviewer=judge, max_revisions=1)})
    await Runner([task], output_dir=tmp_path).run()
    assert [m.content for m in task.episode.messages] == ["first good", "second good"]
    assert len(observations) == 3
    assert observations[2][-3].content == "first good"
    assert observations[2][-2].content == "second bad"
    assert len([e for e in task.episode.events if e["kind"] == "revision"]) == 2


@pytest.mark.parametrize(
    "kind,fallback,accepted",
    [
        ("text", False, False),
        ("text", True, True),
        ("complete", True, False),
        ("tool", True, False),
    ],
)
@pytest.mark.asyncio
async def test_exhaustion_can_accept_only_ordinary_text(
    kind: str, fallback: bool, accepted: bool, tmp_path: Path
) -> None:
    effects: list[str] = []

    async def effect(arguments: Mapping[str, Any]) -> Any:
        effects.append("effect")
        return {}

    class Rejected(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            if kind == "tool":
                return Message(
                    "assistant", tool_calls=(ToolCall("call", FunctionCall("effect")),)
                )
            return Message(
                "assistant", "draft", control="complete" if kind == "complete" else None
            )

    agent = Rejected(
        tools=[Tool(effect)],
        reviewer=Judge(check=lambda messages: False),
        max_revisions=0,
        accept_on_revision_exhaustion=fallback,
    )
    task = Task(agents={"assistant": agent})
    await Runner([task], output_dir=tmp_path).run()
    assert bool(task.episode.messages) is accepted and not effects
    assert task.episode.generation["state"] == (
        "terminated" if accepted else "truncated"
    )
    event = next(e for e in task.episode.events if e["kind"] == "review_exhausted")
    assert event["data"]["accepted"] is accepted


@pytest.mark.asyncio
async def test_malformed_review_never_approves_and_user_cannot_complete(
    tmp_path: Path,
) -> None:
    invalid = Task(
        agents={
            "assistant": Reply(reviewer=Judge(check=lambda messages: {"passed": 1}))
        }
    )
    user = Task(agents={"assistant": Reply(), "user": Reply()})
    episodes = await Runner([invalid, user], output_dir=tmp_path).run()
    assert all(e.status == "failed" and not e.messages for e in episodes)


@pytest.mark.asyncio
async def test_explicit_shared_tool_has_separate_private_exchanges_for_both_roles(
    tmp_path: Path,
) -> None:
    effects: list[str] = []

    async def lookup(arguments: Mapping[str, Any]) -> Any:
        effects.append(arguments["role"])
        return arguments

    class Caller(Agent):
        async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
            role = kwargs["role"]
            if any(m.role == "tool" for m in history):
                return Message(
                    "assistant",
                    role + " done",
                    control="complete" if role == "assistant" else None,
                )
            return Message(
                "assistant",
                tool_calls=(
                    ToolCall("same-id", FunctionCall("lookup", {"role": role})),
                ),
            )

    shared = Caller(tools=[Tool(lookup)])
    task = Task(agents={"assistant": shared, "user": shared})
    await Runner([task], output_dir=tmp_path).run()
    assert effects == ["user", "assistant"]
    assert all(
        m.actor_id == "user"
        for m in task.episode.history("user")
        if m.visibility == "private"
    )
    assert all(
        m.actor_id == "assistant"
        for m in task.episode.history("assistant")
        if m.visibility == "private"
    )
    assert task.episode.training_messages() == [
        {"role": "user", "content": "user done"},
        {"role": "assistant", "content": "assistant done"},
    ]
    with pytest.raises(ValueError):
        Caller(tools=[Tool(lookup), Tool(lookup)])


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
    [{"x": float("nan")}, {"x": float("inf")}, {"x": object()}, {1: "x"}, []],
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
        Task(agents={"assistant": Reply()}, input=[])  # type: ignore[arg-type]
