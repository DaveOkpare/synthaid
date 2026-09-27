"""Final quality decisions through Runner, sealed snapshots, and Dataset export."""

import asyncio
import json
import shutil
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import cast

import pytest

from agentinstruct import (
    Rubric,
    Runner,
    TaskPackage,
    TaskValidationError,
    TraceSnapshot,
    VerificationResult,
    export_native,
    export_openai,
    load_trace,
    reverify,
)
from agentinstruct.execution import (
    Agents,
    Interaction,
    SingleAgentEnvironment,
    TaskContext,
)
from agentinstruct.quality import Verdicts
from agentinstruct.traces import GenerationOutcome


def verified_package(root: Path, *, threshold: float = 0.75) -> TaskPackage:
    source = Path(__file__).resolve().parents[1] / "examples" / "scripted-single"
    shutil.copytree(source, root)
    with (root / "task.toml").open("a") as config:
        config.write('\n[verifier]\ntype = "custom"\ntimeout_seconds = 0.1\n')
    (root / "verifier").mkdir()
    (root / "verifier" / "rubric.toml").write_text(
        f"""threshold = {threshold}
[[criteria]]
id = "helpful"
description = "The response helps the user."
weight = 3.0
[[criteria]]
id = "concise"
description = "The response is concise."
weight = 1.0
"""
    )
    return TaskPackage.load(root)


class MixedJudge:
    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        return VerificationResult(
            criteria={"helpful": bool(trace.conversation), "concise": False},
            feedback="Helpful, but could be shorter.",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("threshold, expected", [(0.75, "accepted"), (0.8, "rejected")])
async def test_weighted_verification_sets_status_and_default_export_eligibility(
    tmp_path: Path, threshold: float, expected: str
) -> None:
    package = verified_package(tmp_path / "task", threshold=threshold)
    result = await Runner(
        output_dir=tmp_path / "runs",
        verifier_factory=lambda _: MixedJudge(),
    ).run(package)

    assert result.traces[0].status == expected
    trace = load_trace(result.traces[0].path)
    assert trace.status == expected
    attempt = trace.verification[0]
    assert attempt.score == 0.75
    assert attempt.status == expected
    assert attempt.feedback == "Helpful, but could be shorter."
    assert attempt.schema_version == "1"
    assert attempt.sequence == 1
    assert attempt.verifier.reference.endswith(":MixedJudge")
    assert attempt.verifier.digest
    assert trace.selected_verification_id == attempt.id
    assert trace.run_plan["verifier"] is not None
    assert (result.path / "source-task" / "verifier" / "rubric.toml").is_file()
    assert export_openai([result.traces[0].path], tmp_path / "dataset.jsonl") == (
        1 if expected == "accepted" else 0
    )


class BrokenJudge:
    def __init__(self, response: object) -> None:
        self.response = response

    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        if self.response == "exception":
            raise RuntimeError("judge unavailable")
        if self.response == "timeout":
            await asyncio.Event().wait()
        if self.response == "malformed":
            return cast(VerificationResult, "not a structured result")
        return VerificationResult(cast(Verdicts, self.response))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response, kind",
    [
        ({"helpful": True}, "malformed"),
        ({"helpful": True, "concise": False, "unknown": True}, "malformed"),
        ({"helpful": True, "concise": 0}, "malformed"),
        ({"helpful": True, "concise": "false"}, "malformed"),
        ([("helpful", True), ("concise", False), ("helpful", False)], "malformed"),
        ("malformed", "malformed"),
        ("exception", "execution"),
        ("timeout", "timeout"),
    ],
)
async def test_verifier_errors_remain_unverified_without_false_evidence(
    tmp_path: Path, response: object, kind: str
) -> None:
    result = await asyncio.wait_for(
        Runner(
            output_dir=tmp_path / "runs",
            verifier_factory=lambda _: BrokenJudge(response),
        ).run(verified_package(tmp_path / "task")),
        timeout=2,
    )

    assert result.counts["unverified"] == 1
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert trace.generation.state == "terminated"
    assert len(trace.conversation) == 1
    attempt = trace.verification[0]
    assert attempt.status == "unverified"
    assert attempt.score is None
    assert attempt.criteria == {}
    assert attempt.error is not None and attempt.error.kind == kind
    assert trace.selected_verification_id is None
    assert export_openai([result.traces[0].path], tmp_path / "dataset.jsonl") == 0


@pytest.mark.asyncio
async def test_reverification_appends_attempts_and_selects_valid_decisions(
    tmp_path: Path,
) -> None:
    package = verified_package(tmp_path / "task")
    result = await Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    ).run(package)
    path = result.traces[0].path
    original = load_trace(path)
    first = original.verification[0]
    sealed_bytes = {
        name: (path / name).read_bytes()
        for name in (
            "trace.json",
            "conversation.jsonl",
            "events.jsonl",
            "run-plan.json",
        )
    }
    first_bytes = (path / "verification" / f"{first.id}.json").read_bytes()
    assert package.verifier is not None
    stricter = replace(
        package.verifier, rubric=Rubric(package.verifier.rubric.criteria, 1.0)
    )

    second = await reverify(
        path, plan=stricter, verifier_factory=lambda _: MixedJudge()
    )
    third = await reverify(path, verifier_factory=lambda _: BrokenJudge("exception"))

    latest = load_trace(path)
    assert [attempt.sequence for attempt in latest.verification] == [1, 2, 3]
    assert len({attempt.id for attempt in latest.verification}) == 3
    assert [attempt.status for attempt in latest.verification] == [
        "accepted",
        "rejected",
        "unverified",
    ]
    assert latest.selected_verification_id == second.id
    assert latest.status == "rejected"
    assert latest.conversation == original.conversation
    assert {name: (path / name).read_bytes() for name in sealed_bytes} == sealed_bytes
    assert (path / "verification" / f"{first.id}.json").read_bytes() == first_bytes
    with pytest.raises(FrozenInstanceError):
        second.score = 1.0  # type: ignore[misc]
    with pytest.raises(TypeError):
        second.criteria["helpful"] = False  # type: ignore[index]
    dataset = tmp_path / "dataset.jsonl"
    assert export_openai([path], dataset) == 0
    assert export_openai([path], dataset, verification_id=first.id) == 1
    assert export_openai([path], dataset, statuses={"rejected"}) == 1
    for invalid_selection in (third.id, "missing"):
        with pytest.raises(ValueError, match="Verification"):
            export_openai([path], dataset, verification_id=invalid_selection)


@pytest.mark.asyncio
async def test_native_export_remains_a_complete_verifiable_source_away_from_run(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    ).run(verified_package(tmp_path / "task"))
    original = load_trace(result.traces[0].path)
    archive = tmp_path / "archive" / "trace.json"
    archive.parent.mkdir()
    assert export_native([result.traces[0].path], archive) == 1

    copied = load_trace(archive)
    assert copied == original
    assert export_openai([archive], tmp_path / "dataset.jsonl") == 1
    shutil.copytree(
        result.traces[0].path / "verification", archive.parent / "verification"
    )
    assert load_trace(archive) == original

    attempt = await reverify(archive, verifier_factory=lambda _: MixedJudge())
    extended = load_trace(archive)
    assert extended.verification == (*original.verification, attempt)
    assert extended.selected_verification_id == attempt.id
    assert original.verification[0].sequence == 1 and attempt.sequence == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("second_name", ["b.json", "trace.json"])
async def test_neighboring_native_snapshots_reverify_independently(
    tmp_path: Path, second_name: str
) -> None:
    package = verified_package(tmp_path / "task")
    runner = Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    )
    first_run = await runner.run(package)
    second_run = await runner.run(package)
    originals = [
        load_trace(first_run.traces[0].path),
        load_trace(second_run.traces[0].path),
    ]
    archive = tmp_path / "archive"
    archive.mkdir()
    first, second = archive / "a.json", archive / second_name
    assert export_native([first_run.traces[0].path], first) == 1
    assert export_native([second_run.traces[0].path], second) == 1
    original_bytes = {path: path.read_bytes() for path in (first, second)}
    assert package.verifier is not None
    stricter = replace(
        package.verifier, rubric=Rubric(package.verifier.rubric.criteria, 1.0)
    )

    first_attempt = await reverify(
        first, plan=stricter, verifier_factory=lambda _: MixedJudge()
    )
    assert load_trace(second) == originals[1]
    second_attempt = await reverify(second, verifier_factory=lambda _: MixedJudge())

    assert first_attempt.sequence == second_attempt.sequence == 2
    assert first_attempt.trace_id != second_attempt.trace_id
    first_snapshot, second_snapshot = load_trace(first), load_trace(second)
    assert first_snapshot.verification == (*originals[0].verification, first_attempt)
    assert second_snapshot.verification == (*originals[1].verification, second_attempt)
    dataset = tmp_path / "dataset.jsonl"
    assert export_openai([first], dataset) == 0
    assert export_openai([first], dataset, statuses={"rejected"}) == 1
    assert export_openai([second], dataset) == 1

    later = await reverify(first, verifier_factory=lambda _: MixedJudge())
    assert later.sequence == 3
    assert load_trace(second) == second_snapshot
    assert export_openai([first, second], dataset) == 2
    assert {path: path.read_bytes() for path in (first, second)} == original_bytes
    for path, original in zip((first, second), originals, strict=True):
        assert load_trace(path).conversation == original.conversation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption, error",
    [("foreign", "different Trace"), ("conflicting", "Conflicting copies")],
)
async def test_native_snapshots_reject_invalid_embedded_verification_evidence(
    tmp_path: Path, corruption: str, error: str
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    ).run(verified_package(tmp_path / "task"))
    archive = tmp_path / "native.json"
    assert export_native([result.traces[0].path], archive) == 1
    native = json.loads(archive.read_text())
    if corruption == "foreign":
        native["verification"][0]["trace_id"] = "another-trace"
    else:
        duplicate = dict(native["verification"][0])
        duplicate["feedback"] = "Altered evidence for the same immutable attempt."
        native["verification"].append(duplicate)
    archive.write_text(json.dumps(native))

    with pytest.raises(ValueError, match=error):
        load_trace(archive)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rubric_text",
    [
        "threshold = 0.5\ncriteria = []",
        *[
            f'[[criteria]]\nid = "helpful"\nweight = {weight}'
            for weight in ("0.0", "-1.0", "inf", "nan", "true")
        ],
        *[
            f'threshold = {threshold}\n[[criteria]]\nid = "helpful"'
            for threshold in ("-0.1", "1.1", "inf", "nan", "true")
        ],
        '[[criteria]]\nid = "helpful"\n[[criteria]]\nid = "helpful"',
        '[[criteria]]\nid = "helpful"\n[[criteria]]\nid = "Helpful"',
        '[[criteria]]\nid = "first"\nweight = 1e308\n'
        '[[criteria]]\nid = "second"\nweight = 1e308',
    ],
)
async def test_invalid_criteria_fail_before_generation(
    tmp_path: Path, rubric_text: str
) -> None:
    package = verified_package(tmp_path / "task")
    (package.root / "verifier" / "rubric.toml").write_text(rubric_text)

    with pytest.raises(TaskValidationError, match=r"verifier/rubric\.toml"):
        await Runner(output_dir=tmp_path / "runs").run(TaskPackage.load(package.root))

    assert not (tmp_path / "runs").exists()


@pytest.mark.asyncio
async def test_deterministic_verifier_runs_without_a_judge_or_provider(
    tmp_path: Path,
) -> None:
    package = verified_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace('type = "custom"', 'type = "deterministic"')
        + '\n[verifier.checks]\nhelpful = "nonempty_conversation"\n'
        'concise = "generation_terminated"\n'
    )

    result = await Runner(output_dir=tmp_path / "runs").run(
        TaskPackage.load(package.root)
    )

    assert result.counts["accepted"] == 1
    trace = load_trace(result.traces[0].path)
    assert trace.verification[0].score == 1.0
    assert trace.verification[0].criteria == {"helpful": True, "concise": True}
    assert trace.verification[0].verifier.reference.endswith(":DeterministicVerifier")


class RetainingEnvironment(SingleAgentEnvironment):
    interaction: Interaction | None = None
    finalized = False

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        async with agents["assistant"].interaction(task) as interaction:
            self.interaction = interaction
            await interaction.turn()
        return GenerationOutcome("terminated", "completed")

    async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
        self.finalized = True


class SealedJudge:
    def __init__(self, environment: RetainingEnvironment, root: Path) -> None:
        self.environment = environment
        self.root = root

    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        assert self.environment.finalized
        assert self.environment.interaction is not None
        persisted = self.root / trace.run_id / "traces" / trace.trace_id
        assert load_trace(persisted) == trace
        with pytest.raises(FrozenInstanceError):
            trace.conversation[0].message.content = "changed"  # type: ignore[misc]
        with pytest.raises(TypeError):
            trace.run_plan["agents"] = {}  # type: ignore[index]
        with pytest.raises(RuntimeError, match="sealed"):
            await self.environment.interaction.turn()
        return VerificationResult({"helpful": True, "concise": True})


@pytest.mark.asyncio
async def test_verifier_sees_finalized_immutable_trace_and_cannot_extend_generation(
    tmp_path: Path,
) -> None:
    package = verified_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'responses = ["Hello, Ada."]', 'responses = ["Hello, Ada.", "Late reply."]'
        )
    )
    environment = RetainingEnvironment()
    root = tmp_path / "runs"

    result = await Runner(
        output_dir=root,
        environment_factory=lambda _: environment,
        verifier_factory=lambda _: SealedJudge(environment, root),
    ).run(TaskPackage.load(package.root))

    assert result.counts["accepted"] == 1
    trace = load_trace(result.traces[0].path)
    assert [commit.message.content for commit in trace.conversation] == ["Hello, Ada."]
    assert (
        len((result.traces[0].path / "conversation.jsonl").read_text().splitlines())
        == 1
    )


class FailedFinalization(SingleAgentEnvironment):
    async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
        raise RuntimeError("cleanup failed after accepted reply")


@pytest.mark.asyncio
async def test_passing_verification_cannot_promote_failed_generation(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        environment_factory=lambda _: FailedFinalization(),
        verifier_factory=lambda _: MixedJudge(),
    ).run(verified_package(tmp_path / "task"))
    assert result.counts["failed"] == 1
    path = result.traces[0].path
    attempt = await reverify(path, verifier_factory=lambda _: MixedJudge())
    trace = load_trace(path)
    assert attempt.status == "accepted"
    assert trace.status == "failed"
    assert trace.generation.state == "failed"
    assert len(trace.conversation) == 1
    dataset = tmp_path / "dataset.jsonl"
    assert export_openai([path], dataset) == 0
    assert export_openai([path], dataset, verification_id=attempt.id) == 0
    assert export_openai([path], dataset, statuses={"failed"}) == 1
