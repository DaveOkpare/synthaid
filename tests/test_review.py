"""Review behavior through the Runner, durable Trace, and Dataset boundaries."""

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from agentinstruct import (
    Message,
    Observation,
    ReviewRequest,
    ReviewResult,
    Runner,
    TaskPackage,
    TaskValidationError,
    TraceSnapshot,
    VerificationResult,
    export_openai,
    load_trace,
)
from agentinstruct.plans import AgentPlan
from agentinstruct.quality import Verdicts


def make_review_package(root: Path, *, policy: str = "") -> TaskPackage:
    root.mkdir()
    config = root / "task.toml"
    config.write_text(
        """schema_version = "1"
[task]
id = "reviewed-dialogue"
version = "1"
[seed]
path = "seed.json"
[variables]
name = "name"
[providers.default]
type = "openai"
[model]
provider = "default"
name = "unused-model"
[runtime]
type = "local"
[environment]
type = "dialogue"
max_rounds = 1
[agents.user]
target = false
[agents.assistant]
target = true
[agents.user.reviewer]
type = "custom"
"""
        + policy,
        encoding="utf-8",
    )
    (root / "seed.json").write_text('{"name":"Ada"}', encoding="utf-8")
    for actor in ("user", "assistant"):
        directory = root / "agents" / actor
        directory.mkdir(parents=True)
        (directory / "instruction.md").write_text(f"You are {actor}.")
    (root / "agents/user/reviewer.md").write_text(
        "Review messages for {{ name }}.", encoding="utf-8"
    )
    (root / "agents/user/rubric.toml").write_text(
        """threshold = 0.75
[[criteria]]
id = "clear"
weight = 3.0
[[criteria]]
id = "complete"
weight = 1.0
""",
        encoding="utf-8",
    )
    return TaskPackage.load(root)


class RevisingAgent:
    def __init__(self, plan: AgentPlan) -> None:
        self.actor = plan.id

    async def generate(self, observation: Observation) -> Message:
        if self.actor == "assistant":
            return Message(
                "assistant",
                json.dumps(
                    {
                        "seen": [message.content for message in observation.messages],
                        "revised": observation.review_feedback is not None,
                    }
                ),
                control="complete",
            )
        if observation.review_feedback is None:
            return Message("assistant", "rejected draft")
        return Message(
            "assistant",
            "revised; feedback_correct="
            f"{observation.review_feedback == 'Review messages for Ada. Be clearer.'}; "
            f"history={len(observation.messages)}",
        )


class WeightedReviewer:
    async def review(self, request: ReviewRequest) -> ReviewResult:
        clear = request.message.content.startswith("revised")
        return ReviewResult(
            {"clear": clear, "complete": False},
            request.instruction + " Be clearer.",
        )


class RejectingReviewer:
    async def review(self, request: ReviewRequest) -> ReviewResult:
        return ReviewResult(
            {criterion.id: False for criterion in request.rubric.criteria}
        )


@pytest.mark.asyncio
async def test_only_weighted_accepted_revision_is_committed_relayed_and_exported(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=RevisingAgent,
        reviewer_factory=lambda _: WeightedReviewer(),
    ).run(make_review_package(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    accepted = "revised; feedback_correct=True; history=0"
    assert trace.generation.state == "terminated"
    assert [item.message.content for item in trace.conversation] == [
        accepted,
        json.dumps({"seen": [accepted], "revised": False}),
    ]
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert [event.data["score"] for event in reviews] == [0.0, 0.75]
    assert [event.data["accepted"] for event in reviews] == [False, True]
    rejection = next(event for event in trace.events if event.kind == "rejection")
    rejected = rejection.data["message"]
    assert isinstance(rejected, Mapping)
    assert rejected["content"] == "rejected draft"
    commit = trace.conversation[0]
    assert commit.review_id == reviews[1].data["review_id"]
    assert reviews[1].data["message_id"] == commit.message.id
    assert reviews[0].data["review_id"] == rejection.data["review_id"]
    assert {event.actor_id for event in reviews} == {"user"}
    assert {event.turn_id for event in reviews} == {commit.turn_id}
    assert any(item.kind == "reviewer:user" for item in trace.components)
    dataset = tmp_path / "dataset.jsonl"
    assert export_openai([result.traces[0].path], dataset, statuses={"unverified"}) == 1
    assert "rejected draft" not in dataset.read_text()
    assert "Be clearer" not in dataset.read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("max_revisions", [0, 1, 2])
async def test_exhaustion_truncates_after_exactly_the_additional_revision_budget(
    tmp_path: Path, max_revisions: int
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=RevisingAgent,
        reviewer_factory=lambda _: RejectingReviewer(),
    ).run(
        make_review_package(
            tmp_path / "task", policy=f"max_revisions = {max_revisions}"
        )
    )

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "truncated"
    assert trace.generation.reason == "review_exhausted"
    assert result.counts["unverified"] == 1
    assert trace.conversation == ()
    assert (
        len([event for event in trace.events if event.kind == "rejection"])
        == max_revisions + 1
    )
    assert (
        len([event for event in trace.events if event.kind == "revision"])
        == max_revisions
    )


class CompletingReviewedAgent(RevisingAgent):
    async def generate(self, observation: Observation) -> Message:
        return replace(await super().generate(observation), control="complete")


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [False, True])
async def test_explicit_exhaustion_fallback_accepts_only_conversation_not_controls(
    tmp_path: Path, control: bool
) -> None:
    package = make_review_package(
        tmp_path / "task",
        policy="max_revisions = 1\naccept_on_revision_exhaustion = true",
    )
    if control:
        config = package.root / "task.toml"
        config.write_text(
            config.read_text()
            .replace("[agents.user]\ntarget = false", "[agents.user]\ntarget = true")
            .replace(
                "[agents.assistant]\ntarget = true",
                "[agents.assistant]\ntarget = false",
            )
        )
        package = TaskPackage.load(package.root)
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=CompletingReviewedAgent if control else RevisingAgent,
        reviewer_factory=lambda _: RejectingReviewer(),
    ).run(package)

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == ("truncated" if control else "terminated")
    assert len(trace.conversation) == (0 if control else 2)
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert len(reviews) == 2
    assert all(event.data["accepted"] is False for event in reviews)
    if not control:
        commit = trace.conversation[0]
        assert commit.review_exhausted is True
        assert commit.review_id == reviews[-1].data["review_id"]
        assert commit.message.content.startswith("revised")
        assert trace.conversation[1].review_exhausted is False


class ListRevisingAgent:
    def __init__(self, plan: AgentPlan) -> None:
        self.actor = plan.id

    async def generate(self, observation: Observation) -> Message | list[Message]:
        if self.actor == "assistant":
            return Message(
                "assistant",
                json.dumps(
                    {
                        "seen": [message.content for message in observation.messages],
                        "feedback": observation.review_feedback,
                    }
                ),
                control="complete",
            )
        if observation.review_feedback is None:
            return [Message("assistant", "bad-first"), Message("assistant", "bad-last")]
        if observation.review_feedback == "bad-first|":
            return [
                Message("assistant", "good-first"),
                Message("assistant", "bad-added"),
            ]
        if observation.review_feedback == "bad-added|good-first":
            return [Message("assistant", "good-added")]
        if observation.review_feedback == "bad-last|good-first,good-added":
            return Message("assistant", "good-last")
        return Message("assistant", "unexpected history or feedback")


class HistoryReviewer:
    async def review(self, request: ReviewRequest) -> ReviewResult:
        history = ",".join(message.content for message in request.messages)
        return ReviewResult(
            {
                criterion.id: request.message.content.startswith("good")
                for criterion in request.rubric.criteria
            },
            f"{request.message.content}|{history}",
        )


@pytest.mark.asyncio
async def test_initial_and_revised_lists_review_each_message_with_its_own_budget(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=ListRevisingAgent,
        reviewer_factory=lambda _: HistoryReviewer(),
    ).run(make_review_package(tmp_path / "task", policy="max_revisions = 1"))

    trace = load_trace(result.traces[0].path)
    accepted = ["good-first", "good-added", "good-last"]
    assert trace.generation.state == "terminated"
    assert [commit.message.content for commit in trace.conversation] == [
        *accepted,
        json.dumps({"seen": accepted, "feedback": None}),
    ]
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert [event.data["accepted"] for event in reviews] == [False, True] * 3
    revisions = [event for event in trace.events if event.kind == "revision"]
    assert [event.data["revision"] for event in revisions] == [1, 1, 1]
    assert [commit.review_id for commit in trace.conversation[:-1]] == [
        event.data["review_id"] for event in reviews if event.data["accepted"]
    ]
    rejected = [event for event in trace.events if event.kind == "rejection"]
    for rejection, revision in zip(rejected, revisions, strict=True):
        message = rejection.data["message"]
        assert isinstance(message, Mapping)
        assert revision.data["revises_message_id"] == message["id"]
        assert revision.data["review_id"] == rejection.data["review_id"]


class InvalidReviewer:
    def __init__(self, result: object) -> None:
        self.result = result

    async def review(self, request: ReviewRequest) -> ReviewResult:
        if isinstance(self.result, Exception):
            raise self.result
        return cast(ReviewResult, self.result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdict", "error_kind"),
    [
        (ReviewResult({"clear": True}), "malformed"),
        (ReviewResult({"clear": True, "complete": True, "unknown": True}), "malformed"),
        (
            ReviewResult([("clear", True), ("complete", True), ("clear", True)]),
            "malformed",
        ),
        (ReviewResult(cast(Verdicts, {"clear": 1, "complete": True})), "malformed"),
        (ReviewResult(cast(Verdicts, [("clear", True, False)])), "malformed"),
        (ReviewResult({"clear": True, "complete": True}, cast(str, None)), "malformed"),
        ({"criteria": {"clear": True, "complete": True}}, "malformed"),
        (RuntimeError("Reviewer unavailable"), "execution"),
    ],
)
async def test_invalid_review_fails_with_linked_evidence_and_cannot_use_fallback(
    tmp_path: Path, verdict: object, error_kind: str
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=RevisingAgent,
        reviewer_factory=lambda _: InvalidReviewer(verdict),
    ).run(
        make_review_package(
            tmp_path / "task",
            policy="max_revisions = 0\naccept_on_revision_exhaustion = true",
        )
    )

    trace = load_trace(result.traces[0].path)
    assert result.counts["failed"] == 1
    assert trace.conversation == ()
    assert trace.generation.reason == f"review_{error_kind}"
    request = next(event for event in trace.events if event.kind == "review_requested")
    error = next(event for event in trace.events if event.kind == "review_error")
    assert error.data["kind"] == error_kind
    assert error.data["review_id"] == request.data["review_id"]
    assert error.data["message_id"] == request.data["message_id"]
    assert error.turn_id == request.turn_id
    assert not any(
        event.kind in {"review_result", "revision"} for event in trace.events
    )


@pytest.mark.asyncio
async def test_offline_review_package_runs_scripted_revisions_and_final_verification(
    tmp_path: Path,
) -> None:
    package = TaskPackage.load(Path(__file__).parents[1] / "examples/reviewed-dialogue")
    result = await Runner(output_dir=tmp_path / "runs").run(package)

    trace = load_trace(result.traces[0].path)
    assert result.counts["accepted"] == 1
    assert [commit.message.content for commit in trace.conversation] == [
        "Hello, Ada.",
        "Welcome, Ada.",
    ]
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert [event.data["score"] for event in reviews] == [0.0, 1.0]
    requests = [event for event in trace.events if event.kind == "review_requested"]
    for event in requests:
        request = event.data["request"]
        assert isinstance(request, Mapping)
        assert request["instruction"] == "Require a nonempty greeting for Ada.\n"
    assert (
        result.path / "source-task/agents/user/reviewer.md"
    ).read_text() == "Require a nonempty greeting for {{ name }}.\n"


class StatefulReviewer:
    def __init__(self) -> None:
        self.attempts = 0

    async def review(self, request: ReviewRequest) -> ReviewResult:
        self.attempts += 1
        return ReviewResult(
            [
                (criterion.id, self.attempts == 2)
                for criterion in request.rubric.criteria
            ],
            f"attempt {self.attempts}",
        )


@pytest.mark.asyncio
async def test_each_agent_and_trace_get_fresh_reviewer_state_and_gate_completion(
    tmp_path: Path,
) -> None:
    package = make_review_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text() + '\n[agents.assistant.reviewer]\ntype = "custom"\n'
    )
    for filename in ("reviewer.md", "rubric.toml"):
        (package.root / "agents/assistant" / filename).write_text(
            (package.root / "agents/user" / filename).read_text()
        )
    package = TaskPackage.load(package.root)
    runner = Runner(
        output_dir=tmp_path / "runs",
        agent_factory=RevisingAgent,
        reviewer_factory=lambda _: StatefulReviewer(),
    )
    first = await runner.run(package)
    second = await runner.run(package)
    for result in (first, second):
        trace = load_trace(result.traces[0].path)
        assert trace.generation.state == "terminated"
        assert len(trace.conversation) == 2
        assert trace.conversation[-1].message.control == "complete"
        reviews = [event for event in trace.events if event.kind == "review_result"]
        assert [(event.actor_id, event.data["accepted"]) for event in reviews] == [
            ("user", False),
            ("user", True),
            ("assistant", False),
            ("assistant", True),
        ]
        assert trace.conversation[-1].review_id == reviews[-1].data["review_id"]
        assert all(not commit.review_exhausted for commit in trace.conversation)
    assert first.traces[0].trace_id != second.traces[0].trace_id


class IndependentVerifier:
    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        return VerificationResult({"clear": True, "complete": False})


@pytest.mark.asyncio
async def test_passing_review_does_not_imply_passing_the_independent_verifier(
    tmp_path: Path,
) -> None:
    package = make_review_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(config.read_text() + '\n[verifier]\ntype = "custom"\n')
    (package.root / "verifier").mkdir()
    (package.root / "verifier/rubric.toml").write_text(
        (package.root / "agents/user/rubric.toml").read_text().replace("0.75", "1.0")
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=RevisingAgent,
        reviewer_factory=lambda _: WeightedReviewer(),
        verifier_factory=lambda _: IndependentVerifier(),
    ).run(TaskPackage.load(package.root))

    trace = load_trace(result.traces[0].path)
    assert len(trace.conversation) == 2
    assert trace.generation.state == "terminated"
    assert trace.verification[0].score == 0.75
    assert trace.status == "rejected"
    assert result.counts["rejected"] == 1
    assert export_openai([result.traces[0].path], tmp_path / "dataset.jsonl") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "text", "error"),
    [
        ("task.toml", "max_revisions = -1", "max_revisions"),
        ("task.toml", "max_revisions = true", "max_revisions"),
        (
            "task.toml",
            'accept_on_revision_exhaustion = "yes"',
            "accept_on_revision_exhaustion",
        ),
        (
            "agents/user/rubric.toml",
            "threshold = 1.1\ncriteria = []",
            "invalid Rubric: threshold: Input should be less than or equal to 1",
        ),
        ("agents/user/reviewer.md", "{{ undeclared }}", "undeclared Variables"),
    ],
)
async def test_invalid_review_policy_or_templates_fail_before_a_run_starts(
    tmp_path: Path, filename: str, text: str, error: str
) -> None:
    package = make_review_package(tmp_path / "task")
    file = package.root / filename
    file.write_text(file.read_text() + text if filename == "task.toml" else text)

    with pytest.raises(TaskValidationError, match=error):
        await Runner(output_dir=tmp_path / "runs").run(TaskPackage.load(package.root))
    assert not (tmp_path / "runs").exists()


@pytest.mark.asyncio
async def test_review_template_binding_failure_is_indexed_before_generation(
    tmp_path: Path,
) -> None:
    package = make_review_package(tmp_path / "task")
    (package.root / "agents/user/reviewer.md").write_text("{{ name.missing }}")
    result = await Runner(output_dir=tmp_path / "runs").run(
        TaskPackage.load(package.root)
    )
    trace = load_trace(result.traces[0].path)
    assert trace.status == "invalid"
    assert trace.components == ()
    assert trace.conversation == ()
    assert "agents/user/reviewer.md: rendering failed" in str(trace.events[-1].data)


class InvalidRevisionAgent:
    def __init__(self, revision: object) -> None:
        self.revision = revision

    async def generate(self, observation: Observation) -> Message | list[Message]:
        if observation.review_feedback is None:
            return Message("assistant", "bad")
        return cast(Message | list[Message], self.revision)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("revision", "state", "accepted"),
    [
        ([], "failed", []),
        ([Message("assistant", "good"), None], "failed", ["good"]),
        (
            [Message("assistant", "bad-again"), Message("assistant", "good-pending")],
            "truncated",
            [],
        ),
        (
            [
                Message("assistant", "good"),
                Message("assistant", "control", control="complete"),
            ],
            "failed",
            ["good"],
        ),
    ],
)
async def test_invalid_or_exhausted_revision_lists_preserve_only_reviewed_commits(
    tmp_path: Path, revision: object, state: str, accepted: list[str]
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: InvalidRevisionAgent(revision),
        reviewer_factory=lambda _: HistoryReviewer(),
    ).run(make_review_package(tmp_path / "task", policy="max_revisions = 1"))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == state
    assert [commit.message.content for commit in trace.conversation] == accepted
    reviews = {
        event.data["message_id"]: event
        for event in trace.events
        if event.kind == "review_result" and event.data["accepted"]
    }
    for commit in trace.conversation:
        assert commit.review_id == reviews[commit.message.id].data["review_id"]
    assert all(commit.message.actor_id == "user" for commit in trace.conversation)
