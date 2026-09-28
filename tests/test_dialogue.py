"""Dialogue behavior through generation, persisted Traces, and Dataset export."""

import asyncio
import json
from pathlib import Path

import pytest

from agentinstruct import (
    Message,
    Observation,
    Runner,
    TaskPackage,
    TaskValidationError,
    TraceSnapshot,
    export_openai,
    load_trace,
)
from agentinstruct.execution import Agents, DialogueEnvironment, TaskContext
from agentinstruct.plans import AgentPlan


def make_dialogue(
    root: Path,
    *,
    initiator: str = "user",
    target: str = "assistant",
    max_rounds: int = 2,
    extra_environment: str = "",
) -> TaskPackage:
    root.mkdir()
    (root / "task.toml").write_text(
        f'''schema_version = "1"
[task]
id = "dialogue"
version = "1"
[seed]
path = "seed.json"
[providers.default]
type = "openai"
[model]
provider = "default"
name = "unused-model"
[runtime]
type = "local"
[environment]
type = "dialogue"
initiator = "{initiator}"
max_rounds = {max_rounds}
{extra_environment}
[agents.user]
target = {str(target == "user").lower()}
[agents.assistant]
target = {str(target == "assistant").lower()}
''',
        encoding="utf-8",
    )
    (root / "seed.json").write_text('{"id":"dialogue-1"}', encoding="utf-8")
    for actor in ("user", "assistant"):
        instruction = root / "agents" / actor / "instruction.md"
        instruction.parent.mkdir(parents=True)
        instruction.write_text(f"You are the {actor}.", encoding="utf-8")
    return TaskPackage.load(root)


class HistoryAgent:
    """Reports its complete Observation so the durable output proves projection."""

    def __init__(self, plan: AgentPlan) -> None:
        self.actor = plan.id

    async def generate(self, observation: Observation) -> Message:
        history = ",".join(
            message.actor_id or "missing" for message in observation.messages
        )
        return Message(role="assistant", content=f"{self.actor} sees [{history}]")


@pytest.mark.asyncio
@pytest.mark.parametrize("initiator", ["user", "assistant"])
async def test_dialogue_alternates_with_full_history_without_relay_duplicates(
    tmp_path: Path, initiator: str
) -> None:
    result = await Runner(output_dir=tmp_path / "runs", agent_factory=HistoryAgent).run(
        make_dialogue(tmp_path / "task", initiator=initiator)
    )

    trace = load_trace(result.traces[0].path)
    peer = "assistant" if initiator == "user" else "user"
    assert [commit.message.content for commit in trace.conversation] == [
        f"{initiator} sees []",
        f"{peer} sees [{initiator}]",
        f"{initiator} sees [{initiator},{peer}]",
        f"{peer} sees [{initiator},{peer},{initiator}]",
    ]
    ids = [commit.message.id for commit in trace.conversation]
    assert len(set(ids)) == 4
    assert [commit.causal_message_id for commit in trace.conversation] == [
        None,
        *ids[:-1],
    ]
    assert result.counts["unverified"] == 1
    assert trace.generation.state == "truncated"
    assert trace.generation.reason == "max_rounds"


class CompletingAgent:
    def __init__(self, plan: AgentPlan) -> None:
        self.target = plan.target

    async def generate(self, observation: Observation) -> Message:
        return Message(
            role="assistant",
            content=f"reply {len(observation.messages) + 1}",
            control="complete"
            if self.target and len(observation.messages) >= 2
            else None,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["user", "assistant"])
@pytest.mark.parametrize("initiator", ["user", "assistant"])
async def test_accepted_target_completion_terminates_even_on_the_last_allowed_turn(
    tmp_path: Path, target: str, initiator: str
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=CompletingAgent
    ).run(make_dialogue(tmp_path / "task", target=target, initiator=initiator))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert trace.generation.reason == "completed"
    assert trace.status == "unverified"
    assert len(trace.conversation) == (3 if target == initiator else 4)
    completion = trace.conversation[-1].message
    assert completion.actor_id == target
    assert completion.control == "complete"


class CompletingSimulator:
    async def generate(self, observation: Observation) -> Message:
        return Message(role="assistant", content="Finished", control="complete")


@pytest.mark.asyncio
async def test_simulator_cannot_accept_a_task_completion_proposal(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: CompletingSimulator()
    ).run(make_dialogue(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    assert result.counts["failed"] == 1
    assert trace.conversation == ()
    assert any(
        event.kind == "agent_error" and "Target Agent" in str(event.data["message"])
        for event in trace.events
    )
    dataset = tmp_path / "empty.jsonl"
    assert export_openai([result.traces[0].path], dataset, statuses={"failed"}) == 0
    assert dataset.read_text() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("complete", [True, False])
async def test_scripted_dialogue_only_completes_with_an_explicit_control(
    tmp_path: Path, complete: bool
) -> None:
    package = make_dialogue(tmp_path / "task")
    config = package.root / "task.toml"
    control = ', control = "complete"' if complete else ""
    config.write_text(
        config.read_text()
        .replace(
            "[agents.user]",
            '[agents.user]\ntype = "scripted"\nresponses = ["Hello"]',
        )
        .replace(
            "[agents.assistant]",
            '[agents.assistant]\ntype = "scripted"\n'
            f'responses = [{{ content = "Goodbye"{control} }}]',
        ),
        encoding="utf-8",
    )

    result = await Runner(output_dir=tmp_path / "runs").run(
        TaskPackage.load(package.root)
    )

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == ("terminated" if complete else "failed")
    assert [commit.message.content for commit in trace.conversation] == [
        "Hello",
        "Goodbye",
    ]
    assert trace.status == ("unverified" if complete else "failed")


class SlowReplyAgent(HistoryAgent):
    async def generate(self, observation: Observation) -> Message:
        if observation.messages:
            await asyncio.Event().wait()
        return await super().generate(observation)


class FinalizingDialogue(DialogueEnvironment):
    def __init__(self) -> None:
        super().__init__()
        self.finalized: list[TraceSnapshot] = []

    async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
        self.finalized.append(trace)


@pytest.mark.asyncio
async def test_timeout_retains_accepted_history_and_finalizes_the_truncated_trace(
    tmp_path: Path,
) -> None:
    environment = FinalizingDialogue()
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=SlowReplyAgent,
        environment_factory=lambda _: environment,
    ).run(make_dialogue(tmp_path / "task", extra_environment="timeout_seconds = 0.5"))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "truncated"
    assert trace.generation.reason == "timeout"
    assert trace.status == "unverified"
    assert [commit.message.content for commit in trace.conversation] == ["user sees []"]
    assert len(environment.finalized) == 1
    assert environment.finalized[0].generation == trace.generation
    assert environment.finalized[0].conversation == trace.conversation


class SlowHookDialogue(DialogueEnvironment):
    def __init__(self, hook: str) -> None:
        super().__init__()
        self.hook = hook

    async def setup(self, agents: Agents) -> None:
        if self.hook == "setup":
            await asyncio.Event().wait()
        await super().setup(agents)

    async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
        if self.hook == "finalize":
            await asyncio.Event().wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", ["setup", "finalize"])
async def test_timeout_also_bounds_environment_setup_and_finalization(
    tmp_path: Path, hook: str
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=CompletingAgent,
        environment_factory=lambda _: SlowHookDialogue(hook),
    ).run(make_dialogue(tmp_path / "task", extra_environment="timeout_seconds = 0.5"))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "truncated"
    assert trace.generation.reason == "timeout"
    assert len(trace.conversation) == (0 if hook == "setup" else 4)
    assert any(
        event.kind == "error" and event.data["stage"] == f"environment_{hook}"
        for event in trace.events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["user", "assistant"])
async def test_openai_export_requires_explicit_unverified_inclusion_and_uses_the_target(
    tmp_path: Path, target: str
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=CompletingAgent
    ).run(make_dialogue(tmp_path / "task", target=target))
    dataset = tmp_path / "dataset.jsonl"
    paths = [result.traces[0].path]

    assert export_openai(paths, dataset) == 0
    assert dataset.read_text() == ""
    assert export_openai(paths, dataset, statuses={"unverified"}) == 1

    messages = [
        {"role": "assistant" if target == "user" else "user", "content": "reply 1"},
        {"role": "user" if target == "user" else "assistant", "content": "reply 2"},
        {"role": "assistant" if target == "user" else "user", "content": "reply 3"},
    ]
    if target == "assistant":
        messages.append({"role": "assistant", "content": "reply 4"})
    assert json.loads(dataset.read_text()) == {"messages": messages}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("original", "replacement", "error"),
    [
        ("[agents.user]", "[agents.simulator]", "requires user and assistant"),
        ("target = false", "target = true", "exactly one explicit Target Agent"),
        ("target = true", "target = false", "exactly one explicit Target Agent"),
        ("max_rounds = 2", "max_rounds = 0", "greater than 0"),
        ('initiator = "user"', 'initiator = "simulator"', "initiator"),
        ("max_rounds = 2", "max_rounds = 2\nmax_turns = 3", "max_rounds"),
    ],
)
async def test_invalid_dialogue_contracts_fail_before_starting_a_run(
    tmp_path: Path, original: str, replacement: str, error: str
) -> None:
    package = make_dialogue(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace(original, replacement), encoding="utf-8"
    )

    with pytest.raises(TaskValidationError, match=error):
        await Runner(output_dir=tmp_path / "runs", agent_factory=HistoryAgent).run(
            TaskPackage.load(package.root)
        )
    assert not (tmp_path / "runs").exists()


class FailingReplyAgent(HistoryAgent):
    async def generate(self, observation: Observation) -> Message:
        if observation.messages:
            raise TimeoutError("extension timed out")
        return await super().generate(observation)


@pytest.mark.asyncio
async def test_extension_timeout_retains_a_failed_partial_trace_for_explicit_export(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=FailingReplyAgent
    ).run(make_dialogue(tmp_path / "task", extra_environment="timeout_seconds = 10.0"))

    trace = load_trace(result.traces[0].path)
    assert result.counts["failed"] == 1
    assert trace.generation.state == "failed"
    assert trace.generation.reason == "agent_execution"
    assert [commit.message.content for commit in trace.conversation] == ["user sees []"]
    assert any(
        event.kind == "agent_error" and event.data["message"] == "extension timed out"
        for event in trace.events
    )
    paths = [result.traces[0].path]
    dataset = tmp_path / "failed.jsonl"
    assert export_openai(paths, dataset) == 0
    assert export_openai(paths, dataset, statuses={"failed"}) == 1
    assert json.loads(dataset.read_text()) == {
        "messages": [{"role": "user", "content": "user sees []"}]
    }
