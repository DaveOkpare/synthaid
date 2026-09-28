"""Ordered Seed collections through Runner and durable public Trace artifacts."""

import json
import shutil
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from agentinstruct import (
    FunctionCall,
    FunctionTool,
    Message,
    Observation,
    ReviewRequest,
    ReviewResult,
    Runner,
    TaskPackage,
    ToolCall,
    ToolContext,
    TraceSnapshot,
    VerificationResult,
    export_native,
    export_openai,
    generate,
    generate_sync,
    load_trace,
)
from agentinstruct.execution import Agents, SingleAgentEnvironment, TaskContext
from agentinstruct.plans import AgentPlan, FrozenJsonValue, JsonValue, ToolPlan
from agentinstruct.traces import GenerationOutcome


def collection_package(root: Path, source: str, *, suffix: str = "json") -> TaskPackage:
    example = Path(__file__).resolve().parents[1] / "examples" / "verified-single"
    shutil.copytree(example, root)
    config = (
        (root / "task.toml")
        .read_text()
        .replace(
            'path = "seed.json"', f'path = "seeds.{suffix}"\nid_variable = "case_id"'
        )
        .replace("[variables]", '[variables]\ncase_id = "id"')
    )
    (root / "task.toml").write_text(config)
    (root / f"seeds.{suffix}").write_text(source)
    (root / "agents/assistant/instruction.md").write_text("Hello {{ name }}.")
    return TaskPackage.load(root)


def test_compile_seed_detaches_nested_caller_data_and_preserves_plan_digest(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        '{"id":"a","name":"Ada","details":{"city":"Lagos"},'
        '"items":[{"label":"initial"}]}',
    )
    seed = package.compile().seed
    details = {"city": "Lagos"}
    item = {"label": "initial"}
    data: dict[str, FrozenJsonValue] = {
        "id": "a",
        "name": "Ada",
        "details": details,
        "items": (item,),
    }
    plan = package.compile_seed(replace(seed, data=data))
    original_digest, original_json = plan.digest, plan.to_json()

    data["name"] = "Lin"
    details["city"] = "Abuja"
    item["label"] = "changed"

    assert plan.seed.data == seed.data
    assert plan.variables["name"] == "Ada"
    assert plan.agents["assistant"].base_instruction == "Hello Ada."
    assert plan.digest == original_digest
    assert plan.to_json() == original_json


@pytest.mark.asyncio
async def test_json_array_preserves_order_and_finishes_each_trace_before_next_seed(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        '[{"id":"b","name":"Lin"},{"id":"a","name":"Ada"}]',
    )
    output = tmp_path / "runs"
    instructions: list[str] = []

    class ReadingAgent:
        async def generate(self, observation: Observation) -> Message:
            assert observation.messages == ()
            if instructions:
                run_path = next(output.iterdir())
                index = [
                    json.loads(line)
                    for line in (run_path / "traces.jsonl").read_text().splitlines()
                ]
                assert len(index) == 1
                previous = load_trace(run_path / index[0]["path"])
                assert previous.seed_id == "b"
                assert previous.status == index[0]["status"] == "accepted"
                assert previous.verification[0].status == "accepted"
                assert previous.conversation[0].message.content == "Hello Lin."
            instructions.append(observation.instruction)
            return Message("assistant", observation.instruction)

    def agent_factory(plan: AgentPlan) -> ReadingAgent:
        return ReadingAgent()

    result = await Runner(output_dir=output, agent_factory=agent_factory).run(package)

    assert [item.seed_id for item in result.traces] == ["b", "a"]
    assert instructions == ["Hello Lin.", "Hello Ada."]
    assert result.counts["accepted"] == 2
    traces = [load_trace(item.path) for item in result.traces]
    plans = [
        json.loads((item.path / "run-plan.json").read_text()) for item in result.traces
    ]
    assert [plan["seed"]["origin"]["record"] for plan in plans] == [1, 2]
    assert len({trace.run_plan["digest"] for trace in traces}) == 2
    index = (result.path / "traces.jsonl").read_text().splitlines()
    assert len(index) == 2
    assert json.loads((result.path / "manifest.json").read_text())["counts"] == dict(
        result.counts
    )


class OutcomeAgent:
    async def generate(self, observation: Observation) -> Message:
        if "failed" in observation.instruction:
            raise RuntimeError("offline Agent failure")
        return Message("assistant", observation.instruction)


class OutcomeVerifier:
    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        if trace.seed_id == "unverified":
            raise RuntimeError("offline Verifier failure")
        return VerificationResult(
            {"has_reply": trace.seed_id != "rejected", "completed": True}
        )


@pytest.mark.asyncio
async def test_jsonl_indexes_mixed_outcomes_with_precise_invalid_record_evidence(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        '\n{"id":"invalid"}\n\n{broken\n'
        '{"id":"failed","name":"failed"}\n'
        '{"id":"unverified","name":"unverified"}\n'
        '{"id":"rejected","name":"rejected"}\n'
        '{"id":"accepted","name":"accepted"}\n',
        suffix="jsonl",
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: OutcomeAgent(),
        verifier_factory=lambda _: OutcomeVerifier(),
    ).run(package)

    assert result.counts == {
        "invalid": 2,
        "failed": 1,
        "unverified": 1,
        "rejected": 1,
        "accepted": 1,
    }
    assert [item.status for item in result.traces] == [
        "invalid",
        "invalid",
        "failed",
        "unverified",
        "rejected",
        "accepted",
    ]
    traces = [load_trace(item.path) for item in result.traces]
    invalid, malformed = traces[:2]
    assert invalid.seed_id == "invalid"
    assert invalid.run_plan == {}
    assert invalid.seed_record is not None
    assert invalid.seed_record.data == {"id": "invalid"}
    assert invalid.task == package.task
    assert invalid.seed_record.origin.record == 2
    assert not (result.traces[0].path / "run-plan.json").exists()
    assert "Variable 'name'" in str(invalid.events[-1].data)
    assert malformed.seed_record is not None
    assert malformed.seed_record.origin.record == 4
    assert malformed.seed_record.raw == "{broken\n"
    assert "column 2" in str(malformed.events[-1].data)
    plans = [
        json.loads((item.path / "run-plan.json").read_text())
        for item in result.traces[2:]
    ]
    assert [plan["seed"]["origin"]["record"] for plan in plans] == [5, 6, 7, 8]
    index = [
        json.loads(line)
        for line in (result.path / "traces.jsonl").read_text().splitlines()
    ]
    assert [row["status"] for row in index] == [item.status for item in result.traces]
    assert (
        export_native(
            [item.path for item in result.traces],
            tmp_path / "native.jsonl",
            statuses={"invalid"},
        )
        == 2
    )
    assert (
        export_openai(
            [item.path for item in result.traces],
            tmp_path / "openai.jsonl",
            statuses={"invalid", "accepted"},
        )
        == 1
    )


@pytest.mark.asyncio
async def test_duplicate_logical_ids_get_distinct_invalid_attempts_and_later_seeds_run(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        '[{"id":"same"},{"id":"same","name":"duplicate"},{"id":"last","name":"last"}]',
    )
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert [item.seed_id for item in result.traces] == ["same", "same", "last"]
    assert [item.status for item in result.traces] == ["invalid", "invalid", "accepted"]
    assert len({item.trace_id for item in result.traces}) == 3
    assert "duplicate Seed ID" in str(load_trace(result.traces[1].path).events[-1].data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "first, count", [("invalid", 1), ("failed", 1), ("unverified", 2), ("rejected", 2)]
)
async def test_fail_fast_stops_only_invalid_or_failed_attempts(
    tmp_path: Path, first: str, count: int
) -> None:
    data = {"id": first} if first == "invalid" else {"id": first, "name": first}
    package = collection_package(
        tmp_path / "task", json.dumps([data, {"id": "last", "name": "last"}])
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: OutcomeAgent(),
        verifier_factory=lambda _: OutcomeVerifier(),
    ).run(package, fail_fast=True)
    assert len(result.traces) == count
    assert result.traces[0].status == first
    assert result.status == ("stopped" if count == 1 else "finished")
    assert len((result.path / "traces.jsonl").read_text().splitlines()) == count


@pytest.mark.asyncio
async def test_invalid_array_elements_continue_but_syntax_failure_fails_run(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        '[42,{"id":"duplicate-key","name":"a","name":"b"},'
        '{"id":"ok","name":"ok"}, {broken]',
    )
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert result.status == "failed"
    assert [item.status for item in result.traces] == ["invalid", "invalid", "accepted"]
    assert result.error is not None and "malformed JSON" in result.error
    scalar = load_trace(result.traces[0].path)
    assert scalar.seed_record is not None and scalar.seed_record.data == 42
    duplicate = load_trace(result.traces[1].path)
    assert duplicate.seed_record is not None
    assert duplicate.seed_record.origin.record == 2
    assert duplicate.seed_record.raw == '{"id":"duplicate-key","name":"a","name":"b"}'
    assert "duplicate JSON object key" in str(duplicate.events[-1].data)
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["error"] == result.error
    assert manifest["counts"] == dict(result.counts)
    assert len((result.path / "traces.jsonl").read_text().splitlines()) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["[]", " \n\t\n"])
async def test_empty_sources_finish_with_no_invented_attempts(
    tmp_path: Path, source: str
) -> None:
    package = collection_package(
        tmp_path / "task", source, suffix="json" if source == "[]" else "jsonl"
    )
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert result.status == "finished"
    assert result.traces == ()
    assert sum(result.counts.values()) == 0
    assert (result.path / "traces.jsonl").read_text() == ""


@pytest.mark.asyncio
async def test_canonical_hash_ids_are_stable_across_ordering_and_new_attempts(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        '[{"name":"Ada","id":"a"},{"id":"a","name":"Ada"},{"name":"Lin","id":"b"}]',
    )
    config = package.root / "task.toml"
    config.write_text(config.read_text().replace('id_variable = "case_id"\n', ""))
    package = TaskPackage.load(package.root)
    runner = Runner(output_dir=tmp_path / "runs")
    first = await runner.run(package)
    second = await generate(package, runner=runner, fail_fast=True)
    assert [item.status for item in first.traces] == ["accepted", "invalid", "accepted"]
    assert len(first.traces[0].seed_id) == 64
    assert (
        first.traces[0].seed_id == first.traces[1].seed_id == second.traces[0].seed_id
    )
    assert first.traces[0].trace_id != second.traces[0].trace_id
    assert second.status == "stopped"
    assert len(second.traces) == 2


def test_generate_sync_preserves_collection_fail_fast_and_seed_override(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"unused","name":"unused"}')
    source = tmp_path / "override.jsonl"
    source.write_text('{"id":"broken"}\n{"id":"valid","name":"valid"}\n')
    result = generate_sync(
        package,
        runner=Runner(output_dir=tmp_path / "runs"),
        seed_path=source,
        fail_fast=True,
    )
    assert result.status == "stopped"
    assert result.counts["invalid"] == 1
    assert len(result.traces) == 1
    trace = load_trace(result.traces[0].path)
    assert trace.seed_record is not None
    assert trace.seed_record.origin.path == str(source.resolve())


@pytest.mark.asyncio
async def test_each_seed_gets_fresh_agents_reviewers_tools_environment_and_steps(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task", '[{"id":"a","name":"Ada"},{"id":"b","name":"Lin"}]'
    )
    config = package.root / "task.toml"
    config.write_text(
        config.read_text()
        .replace("[task]", '[task]\nsteps = ["collect", "conclude"]')
        .replace("[environment]", "[environment]\nmax_turns = 4")
        .replace("[agents.assistant]", '[agents.assistant]\ntools = ["counter"]')
        + """
[agents.assistant.reviewer]
type = "custom"
max_revisions = 1
[tools.counter]
description = "Count private calls in this Trace"
input_schema = { type = "object", additionalProperties = false }
"""
    )
    (package.root / "agents/assistant/reviewer.md").write_text("Review {{ name }}.")
    (package.root / "agents/assistant/rubric.toml").write_text(
        '[[criteria]]\nid = "base"\n'
    )
    for step in ("collect", "conclude"):
        directory = package.root / f"steps/{step}/agents/assistant"
        directory.mkdir(parents=True)
        (directory / "instruction.md").write_text(f"{step} {{{{ name }}}}.")
        (directory / "rubric.toml").write_text(f'[[criteria]]\nid = "{step}"\n')

    class FreshAgent:
        def __init__(self, plan: AgentPlan) -> None:
            self.base = plan.base_instruction
            self.calls = 0

        async def generate(self, observation: Observation) -> Message:
            self.calls += 1
            if self.calls == 1:
                assert observation.messages == ()
                assert observation.review_feedback is None
                assert observation.step_id == "collect"
                return Message("assistant", "")
            if self.calls == 2:
                assert observation.review_feedback == "Revise the empty proposal"
                assert observation.messages == ()
                return Message(
                    "assistant",
                    tool_calls=(
                        ToolCall("counter-1", FunctionCall("counter", {})),
                        ToolCall("counter-2", FunctionCall("counter", {})),
                    ),
                )
            if self.calls == 3:
                results = [
                    json.loads(message.content)["count"]
                    for message in observation.messages
                    if message.role == "tool"
                ]
                assert results == [1, 2]
                return Message(
                    "assistant",
                    tool_calls=(
                        ToolCall(
                            "advance",
                            FunctionCall("advance_step", {"step_id": "conclude"}),
                        ),
                    ),
                )
            assert observation.step_id == "conclude"
            assert "collect " not in observation.instruction
            if self.calls == 4:
                return Message(
                    "assistant",
                    tool_calls=(
                        ToolCall("complete", FunctionCall("complete_task", {})),
                    ),
                )
            assert self.calls == 5
            assert observation.tools == ()
            return Message("assistant", self.base)

    class FreshReviewer:
        def __init__(self) -> None:
            self.calls = 0

        async def review(self, request: ReviewRequest) -> ReviewResult:
            self.calls += 1
            assert {criterion.id for criterion in request.rubric.criteria} == {
                "base",
                request.step_id,
            }
            if self.calls == 1:
                assert request.message.content == "" and not request.message.tool_calls
                assert request.messages == ()
            return ReviewResult(
                {criterion.id: self.calls > 1 for criterion in request.rubric.criteria},
                "Revise the empty proposal" if self.calls == 1 else "",
            )

    class CounterTool(FunctionTool):
        def __init__(self, plan: ToolPlan) -> None:
            super().__init__(plan, self.execute)
            self.calls = 0

        async def execute(
            self, args: Mapping[str, FrozenJsonValue], context: ToolContext
        ) -> JsonValue:
            self.calls += 1
            return {"count": self.calls, "seed_id": context.seed_id}

    class FreshEnvironment(SingleAgentEnvironment):
        def __init__(self) -> None:
            self.used = False

        async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
            assert not self.used
            self.used = True
            return await super().run(task, agents)

    class FreshVerifier(OutcomeVerifier):
        def __init__(self) -> None:
            self.used = False

        async def verify(self, trace: TraceSnapshot) -> VerificationResult:
            assert not self.used
            self.used = True
            return await super().verify(trace)

    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=FreshAgent,
        reviewer_factory=lambda _: FreshReviewer(),
        tool_factory=CounterTool,
        environment_factory=lambda _: FreshEnvironment(),
        verifier_factory=lambda _: FreshVerifier(),
    ).run(TaskPackage.load(package.root))
    assert result.counts["accepted"] == 2
    traces = [load_trace(item.path) for item in result.traces]
    assert [trace.conversation[-1].message.content for trace in traces] == [
        "Hello Ada.",
        "Hello Lin.",
    ]
    for trace in traces:
        assert len(trace.conversation) == 8
        assert trace.generation.state == "terminated"
        assert [
            event.step_id for event in trace.events if event.kind == "step_started"
        ] == ["collect", "conclude"]


@pytest.mark.asyncio
async def test_index_storage_failure_stops_before_next_seed_and_preserves_snapshot(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task", '[{"id":"first","name":"first"},{"id":"next","name":"next"}]'
    )
    output = tmp_path / "runs"

    class StorageFailureAgent:
        async def generate(self, observation: Observation) -> Message:
            run_path = next(output.iterdir())
            index = run_path / "traces.jsonl"
            index.unlink()
            index.mkdir()
            return Message("assistant", "Already durable when indexing fails")

    result = await Runner(
        output_dir=output, agent_factory=lambda _: StorageFailureAgent()
    ).run(package)
    assert result.status == "failed"
    assert result.error is not None and "persistence" in result.error
    assert len(result.traces) == 1
    trace = load_trace(result.traces[0].path)
    assert trace.seed_id == "first"
    assert trace.status == "accepted"
    assert len(list((result.path / "traces").iterdir())) == 1
    manifest = json.loads((result.path / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["traces"][0]["trace_id"] == trace.trace_id


@pytest.mark.asyncio
async def test_non_json_trailing_whitespace_is_a_source_error(tmp_path: Path) -> None:
    package = collection_package(tmp_path / "task", "[]\u00a0")
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert result.status == "failed"
    assert result.traces == ()
    assert result.error is not None and "Extra data" in result.error


@pytest.mark.asyncio
async def test_jsonl_parser_depth_failure_retains_origin_and_continues(
    tmp_path: Path,
) -> None:
    raw = '{"deep":' + "[" * 1500 + "0" + "]" * 1500 + "}\n"
    package = collection_package(
        tmp_path / "task", raw + '{"id":"ok","name":"ok"}\n', suffix="jsonl"
    )
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert [reference.status for reference in result.traces] == ["invalid", "accepted"]
    invalid = load_trace(result.traces[0].path)
    assert invalid.seed_record is not None and invalid.seed_record.raw == raw
    assert invalid.seed_record.origin.record == 1
