"""Trace generation through the public library and persisted-artifact boundaries."""

import json
from pathlib import Path

import pytest

from agentinstruct import (
    Message,
    Observation,
    Runner,
    TaskPackage,
    export_native,
    generate,
    generate_sync,
    load_trace,
)
from agentinstruct.execution import Agents, SingleAgentEnvironment, TaskContext
from agentinstruct.plans import AgentPlan
from agentinstruct.traces import GenerationOutcome


def make_package(root: Path) -> TaskPackage:
    root.mkdir()
    (root / "task.toml").write_text(
        """schema_version = "1"
[task]
id = "greeting"
version = "1"
[seed]
path = "seed.json"
id_variable = "case_id"
[variables]
case_id = "id"
name = "name"
[providers.default]
type = "openai"
[model]
provider = "default"
name = "unused-model"
[runtime]
type = "local"
[environment]
type = "single"
[agents.assistant]
target = true
""",
        encoding="utf-8",
    )
    (root / "seed.json").write_text('{"id":"case-1","name":"Ada"}')
    instruction = root / "agents" / "assistant" / "instruction.md"
    instruction.parent.mkdir(parents=True)
    instruction.write_text("Greet {{ name }}.", encoding="utf-8")
    return TaskPackage.load(root)


class GreetingAgent:
    def __init__(self, plan: AgentPlan) -> None:
        self.plan = plan

    async def generate(self, observation: Observation) -> Message:
        return Message(
            role="assistant",
            content=f"{observation.instruction} History: {len(observation.messages)}.",
        )


@pytest.mark.asyncio
async def test_single_seed_produces_a_complete_durable_trace(tmp_path: Path) -> None:
    package = make_package(tmp_path / "task")

    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=GreetingAgent
    ).run(package)

    assert result.counts == {
        "invalid": 0,
        "failed": 0,
        "unverified": 1,
        "rejected": 0,
        "accepted": 0,
    }
    assert len(result.traces) == 1
    trace = load_trace(result.traces[0].path)
    assert trace.run_id == result.run_id
    assert trace.seed_id == "case-1"
    assert trace.status == "unverified"
    assert trace.generation.state == "terminated"
    assert trace.generation.reason == "completed"
    assert trace.run_plan["seed"] == {
        "id": "case-1",
        "data": {"id": "case-1", "name": "Ada"},
        "origin": {"path": "seed.json", "record": 1, "format": "json"},
        "digest": package.compile().seed.digest,
    }
    assert len(trace.conversation) == 1
    commit = trace.conversation[0]
    assert commit.message.content == "Greet Ada. History: 0."
    assert commit.message.actor_id == "assistant"
    assert commit.message.id and commit.turn_id
    assert commit.visibility == "shared"
    assert {event.kind for event in trace.events} >= {
        "trace_started",
        "environment_setup",
        "environment_run",
        "proposal",
        "message_committed",
        "generation_finished",
        "trace_finished",
    }
    assert trace.started_at <= trace.ended_at
    assert trace.duration_seconds >= 0
    assert any("GreetingAgent" in item.reference for item in trace.components)
    assert all(item.digest for item in trace.components)
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["counts"]["unverified"] == 1
    assert (result.path / "source-task" / "task.toml").is_file()
    index = json.loads((result.path / "traces.jsonl").read_text())
    assert index["trace_id"] == trace.trace_id
    assert (result.traces[0].path / "run-plan.json").is_file()


class StatefulAgent(GreetingAgent):
    def __init__(self, plan: AgentPlan) -> None:
        super().__init__(plan)
        self.turns = 0

    async def generate(self, observation: Observation) -> Message:
        self.turns += 1
        return Message(
            role="assistant",
            content=f"turn={self.turns};history={len(observation.messages)}",
        )


class FreshEnvironment(SingleAgentEnvironment):
    def __init__(self) -> None:
        self.has_run = False

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        if self.has_run:
            raise RuntimeError("Environment state leaked across Traces")
        self.has_run = True
        return await super().run(task, agents)


@pytest.mark.asyncio
async def test_repeated_runs_use_fresh_state_and_export_from_disk(
    tmp_path: Path,
) -> None:
    package = make_package(tmp_path / "task")
    runner = Runner(
        output_dir=tmp_path / "runs",
        agent_factory=StatefulAgent,
        environment_factory=lambda _: FreshEnvironment(),
    )
    first = await runner.run(package)
    second = await generate(package, runner=runner)
    assert first.run_id != second.run_id
    assert first.traces[0].trace_id != second.traces[0].trace_id
    snapshots = [load_trace(run.traces[0].path) for run in (first, second)]
    assert {trace.seed_id for trace in snapshots} == {"case-1"}
    for trace in snapshots:
        assert trace.status == "unverified"
        assert [item.message.content for item in trace.conversation] == [
            "turn=1;history=0"
        ]
    assert snapshots[0].conversation[0].message.id != (
        snapshots[1].conversation[0].message.id
    )
    export = tmp_path / "dataset.jsonl"
    paths = [first.traces[0].path, second.traces[0].path]
    assert export_native(paths, export) == 0
    assert export.read_text() == ""
    assert export_native(paths, export, statuses={"unverified"}) == 2
    exported = [json.loads(line) for line in export.read_text().splitlines()]
    assert [item["trace_id"] for item in exported] == [
        first.traces[0].trace_id,
        second.traces[0].trace_id,
    ]
    assert exported[0]["conversation"][0]["message"]["content"] == "turn=1;history=0"
    assert (
        exported[0]["run_plan"]["agents"]["assistant"]["base_instruction"]
        == "Greet Ada."
    )


def test_synchronous_generation_uses_the_same_trace_lifecycle(tmp_path: Path) -> None:
    package = make_package(tmp_path / "task")
    result = generate_sync(
        package,
        runner=Runner(output_dir=tmp_path / "runs", agent_factory=GreetingAgent),
    )
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert trace.conversation[0].message.content == "Greet Ada. History: 0."


class FailedEnvironment(SingleAgentEnvironment):
    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        return GenerationOutcome("failed", "environment_stopped")


@pytest.mark.asyncio
async def test_explicit_environment_failure_is_counted_as_failed(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=GreetingAgent,
        environment_factory=lambda _: FailedEnvironment(),
    ).run(make_package(tmp_path / "task"))

    assert result.counts["failed"] == 1
    assert result.counts["unverified"] == 0
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "environment_stopped"
    assert trace.status == "failed"
