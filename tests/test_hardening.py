"""Failure durability and safe diagnostics through public execution boundaries."""

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from agentinstruct import (
    Agents,
    FunctionCall,
    Message,
    Observation,
    Runner,
    TaskContext,
    ToolCall,
    TraceSnapshot,
    VerificationResult,
    load_run,
    load_trace,
    reverify,
)
from agentinstruct.providers import ChatCompletionsProvider
from tests.test_providers import FakeTransport, completion, model_package
from tests.test_tools import LookupTool, make_tool_package
from tests.test_verification import MixedJudge, verified_package


@pytest.mark.asyncio
async def test_external_cancellation_seals_indexes_and_closes_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = model_package(tmp_path / "task")
    monkeypatch.setenv("PROVIDER_TEST_KEY", "runtime-secret")
    transport = FakeTransport(completion("Accepted before cancellation"))
    waiting = asyncio.Event()
    finalized: list[str] = []
    finalizing = asyncio.Event()
    finish_finalizing = asyncio.Event()

    class WaitingEnvironment:
        async def setup(self, agents: Agents) -> None:
            pass

        async def run(self, task: TaskContext, agents: Agents) -> None:
            async with agents["assistant"].interaction(task) as interaction:
                await interaction.turn()
            waiting.set()
            await asyncio.Future[None]()

        async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
            finalized.append(trace.generation.reason)
            finalizing.set()
            await finish_finalizing.wait()

    output = tmp_path / "runs"
    running = asyncio.create_task(
        Runner(
            output_dir=output,
            provider_factory=lambda plan: ChatCompletionsProvider(
                plan, transport=transport
            ),
            environment_factory=lambda _: WaitingEnvironment(),
        ).run(package)
    )
    await asyncio.wait_for(waiting.wait(), 2)
    running.cancel()
    await asyncio.wait_for(finalizing.wait(), 2)
    running.cancel()
    finish_finalizing.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    run = load_run(next(output.iterdir()))
    assert run.manifest["status"] == "failed"
    assert len(run.traces) == 1
    trace = run.traces[0].snapshot
    assert trace.status == "failed" and trace.generation.reason == "cancelled"
    assert [item.message.content for item in trace.conversation] == [
        "Accepted before cancellation"
    ]
    assert finalized == ["cancelled"] and transport.closed


@pytest.mark.asyncio
async def test_cancelled_reverification_appends_unverified_attempt_before_propagating(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    ).run(verified_package(tmp_path / "task"))
    path = result.traces[0].path
    generation = {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}
    waiting = asyncio.Event()

    class WaitingVerifier:
        async def verify(self, trace: TraceSnapshot) -> VerificationResult:
            waiting.set()
            await asyncio.Future[None]()
            raise AssertionError("unreachable")

    running = asyncio.create_task(
        reverify(path, verifier_factory=lambda _: WaitingVerifier())
    )
    await asyncio.wait_for(waiting.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    trace = load_trace(path)
    assert trace.status == "accepted"
    assert len(trace.verification) == 2
    attempt = trace.verification[-1]
    assert attempt.status == "unverified" and attempt.error is not None
    assert attempt.error.kind == "cancelled"
    assert {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()} == generation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad", ["integer_key", "nonfinite", "cycle", "object", "dataclass", "message_name"]
)
async def test_invalid_python_proposals_never_commit_or_execute_tools(
    tmp_path: Path, bad: str
) -> None:
    from collections.abc import Mapping

    from agentinstruct.plans import FrozenJsonValue

    output = tmp_path / "runs"
    package = make_tool_package(tmp_path / "task")
    calls: list[str] = []

    class InvalidAgent:
        async def generate(self, observation: Observation) -> Message:
            if bad == "message_name":
                return Message("assistant", "invalid name", name=cast(str, 42))
            value: object = {1: "coerced"}
            if bad == "nonfinite":
                value = {"value": float("nan")}
            elif bad == "object":
                value = {"value": object()}
            elif bad == "dataclass":
                from dataclasses import dataclass

                @dataclass
                class CustomValue:
                    value: str = "unsupported"

                value = {"value": CustomValue()}
            elif bad == "cycle":
                recursive: list[object] = []
                recursive.append(recursive)
                value = {"value": recursive}
            return Message(
                "assistant",
                tool_calls=(
                    ToolCall(
                        "bad",
                        FunctionCall(
                            "lookup", cast(Mapping[str, FrozenJsonValue], value)
                        ),
                    ),
                ),
            )

    class WatchingTool(LookupTool):
        async def call(
            self, args: Mapping[str, FrozenJsonValue], context: object
        ) -> str:
            calls.append("effect")
            return "unexpected"

    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: InvalidAgent(),
        tool_factory=lambda plan: WatchingTool(plan, output),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and trace.conversation == ()
    assert calls == []
    errors = [event for event in trace.events if event.kind == "agent_error"]
    assert errors and errors[0].actor_id == "assistant"
    assert errors[0].data["proposal_attempt"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}'])
async def test_agent_tool_rejects_non_strict_json_results(
    tmp_path: Path, reply: str
) -> None:
    from agentinstruct import AgentTool
    from tests.test_tools import LookupAgent

    class Subordinate:
        async def generate(self, observation: Observation) -> Message:
            return Message("assistant", reply)

    package = make_tool_package(tmp_path / "task")
    config = package.root / "task.toml"
    text = config.read_text()
    config.write_text(
        text[: text.index("[tools.lookup.output_schema]")]
        + text[text.index("[agents.assistant]") :]
    )
    from agentinstruct import TaskPackage

    package = TaskPackage.load(package.root)
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: AgentTool(
            plan, Subordinate, instruction="Return JSON"
        ),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and trace.generation.reason == "tool_result"
    assert len(trace.conversation) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@example.test/v1",
        "https://example.test/v1?token=secret",
        "https://example.test/#secret",
        "https://example.test/\nsecret",
        "file:///secret",
    ],
)
def test_direct_provider_plans_reject_unsafe_urls_without_echoing_values(
    url: str,
) -> None:
    from agentinstruct import ProviderPlan

    with pytest.raises(ValueError) as failure:
        ProviderPlan("test", "openai", "responses", url, None)
    assert "secret" not in str(failure.value)


@pytest.mark.parametrize(
    "reference", ["Bearer runtime-secret", "BAD=runtime-secret", ""]
)
def test_direct_provider_plan_requires_an_environment_reference(reference: str) -> None:
    from agentinstruct import ProviderPlan

    with pytest.raises(ValueError) as failure:
        ProviderPlan("test", "openai", "responses", None, reference)
    assert "runtime-secret" not in str(failure.value)


@pytest.mark.asyncio
async def test_revision_failures_keep_safe_causes_and_attempt_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentinstruct import TaskPackage
    from tests.test_review import RejectingReviewer, make_review_package

    secret = "configured-runtime-secret-123"
    monkeypatch.setenv("RUNTIME_TEST_KEY", secret)
    package = make_review_package(tmp_path / "task", policy="max_revisions = 1")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'type = "openai"', 'type = "openai"\napi_key_env = "RUNTIME_TEST_KEY"'
        )
    )

    class FailingRevision:
        async def generate(self, observation: Observation) -> Message:
            if observation.review_feedback is None:
                return Message("assistant", "Rejected once")
            try:
                raise ValueError("root cause " + secret)
            except ValueError as exc:
                raise RuntimeError(
                    "Authorization: Bearer unknown-header-secret; " + secret
                ) from exc

    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: FailingRevision(),
        reviewer_factory=lambda _: RejectingReviewer(),
    ).run(TaskPackage.load(package.root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "agent_execution" and not trace.conversation
    error = next(event for event in trace.events if event.kind == "agent_error")
    assert error.actor_id == "user" and error.turn_id is not None and error.timestamp
    assert error.data["stage"] == "agent_generate"
    assert error.data["proposal_attempt"] == 2 and error.data["revision"] == 1
    assert "ValueError" in str(error.data["causes"])
    assert any(event.kind == "rejection" for event in trace.events)
    persisted = b"".join(p.read_bytes() for p in result.path.rglob("*") if p.is_file())
    assert (
        secret.encode() not in persisted and b"unknown-header-secret" not in persisted
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("close_failure", ["exception", "timeout"])
async def test_persistence_failure_does_not_skip_environment_or_other_provider_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, close_failure: str
) -> None:
    from agentinstruct import TaskPackage
    from tests.test_dialogue import make_dialogue

    root, output = tmp_path / "task", tmp_path / "runs"
    make_dialogue(root, extra_environment="timeout_seconds = 0.05")
    config = root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://fake.example/v1"',
        )
        + '\n[providers.other]\ntype="openai-compatible"\nbase_url="https://fake.example/v1"\n[agents.assistant.model]\nprovider="other"\n'
    )
    (root / "seed.json").write_text('[{"id":1},{"id":2}]')
    closed: list[str] = []

    class BadCloseTransport(FakeTransport):
        async def aclose(self) -> None:
            closed.append("first")
            if close_failure == "timeout":
                await asyncio.Future[None]()
            raise RuntimeError("close failed")

    class GoodCloseTransport(FakeTransport):
        async def aclose(self) -> None:
            closed.append("second")

    transports = iter(
        (BadCloseTransport(completion()), GoodCloseTransport(completion()))
    )
    finalized: list[bool] = []

    class BrokenStorageEnvironment:
        async def setup(self, agents: Agents) -> None:
            pass

        async def run(self, task: TaskContext, agents: Agents) -> None:
            async with agents["user"].interaction(task) as interaction:
                await interaction.turn()
            async with agents["assistant"].interaction(task) as interaction:
                await interaction.turn()
            events = next(output.glob("*/traces/*/events.jsonl"))
            events.unlink()
            events.mkdir()
            raise RuntimeError("Later environment failure")

        async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
            finalized.append(True)

    result = await asyncio.wait_for(
        Runner(
            output_dir=output,
            provider_factory=lambda plan: ChatCompletionsProvider(
                plan, transport=next(transports)
            ),
            environment_factory=lambda _: BrokenStorageEnvironment(),
        ).run(TaskPackage.load(root)),
        2,
    )
    assert closed == ["first", "second"] and finalized == [True]
    assert result.status == "failed" and len(result.traces) == 1
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "persistence" and len(trace.conversation) == 2
    assert len(load_run(result.path).traces) == 1


@pytest.mark.asyncio
async def test_secret_redaction_keeps_committed_relay_and_tool_intent_consistent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Mapping

    from agentinstruct import TaskPackage, ToolContext
    from agentinstruct.plans import AgentPlan, FrozenJsonValue, JsonValue

    secret = "configured-effect-secret-321"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    root, output = tmp_path / "task", tmp_path / "runs"
    make_tool_package(root)
    config = root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'type = "single"', 'type = "dialogue"\nmax_rounds = 1'
        )
        + "\n[agents.user]\ntarget=false\n"
    )
    (root / "agents/user").mkdir()
    (root / "agents/user/instruction.md").write_text(
        "Illustrative Authorization: Bearer authored-example"
    )
    (root / "seed.json").write_text('{"name":"Ada","password":"authored-example"}')
    observed: list[str] = []
    effects: list[object] = []

    class SecretAgent:
        def __init__(self, plan: AgentPlan) -> None:
            self.id = plan.id

        async def generate(self, observation: Observation) -> Message:
            if self.id == "user":
                return Message("assistant", "Shared " + secret)
            observed.extend(message.content for message in observation.messages)
            if observation.messages[-1].role == "tool":
                return Message("assistant", "Done", control="complete")
            return Message(
                "assistant",
                tool_calls=(
                    ToolCall("lookup", FunctionCall("lookup", {"label": secret})),
                ),
            )

    class SafeLookup(LookupTool):
        async def call(
            self, args: Mapping[str, FrozenJsonValue], context: ToolContext
        ) -> JsonValue:
            effects.append(args["label"])
            return await super().call(args, context)

    result = await Runner(
        output_dir=output,
        agent_factory=SecretAgent,
        tool_factory=lambda plan: SafeLookup(plan, output),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert effects == ["[REDACTED]"] and "Shared [REDACTED]" in observed
    assert (
        trace.conversation[1].message.tool_calls[0].function.arguments["label"]
        == effects[0]
    )
    persisted = b"".join(p.read_bytes() for p in result.path.rglob("*") if p.is_file())
    assert secret.encode() not in persisted
    assert (
        result.path / "source-task/agents/user/instruction.md"
    ).read_text() == "Illustrative Authorization: Bearer authored-example"
    assert (
        json.loads((result.traces[0].path / "run-plan.json").read_text())["seed"][
            "data"
        ]["password"]
        == "authored-example"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boundary",
    ["source", "source_directory", "conversation.jsonl", "events.jsonl", "artifacts"],
)
async def test_storage_sync_failure_prevents_execution_and_index_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    import os

    from tests.test_runner import GreetingAgent, make_package

    output = tmp_path / "runs"
    package = make_package(tmp_path / "task")
    fsync = os.fsync
    attempted: list[str] = []
    generated: list[str] = []

    def sync(descriptor: int) -> None:
        pattern = (
            "*/source-task/agents/assistant/instruction.md"
            if boundary == "source"
            else "*/source-task/agents/assistant"
            if boundary == "source_directory"
            else f"*/traces/*/{boundary}"
        )
        for target in output.glob(pattern):
            if os.fstat(descriptor).st_ino == target.stat().st_ino:
                attempted.append(boundary)
                raise OSError("Controlled storage sync failure")
        fsync(descriptor)

    class ObservedAgent(GreetingAgent):
        async def generate(self, observation: Observation) -> Message:
            generated.append("called")
            return await super().generate(observation)

    monkeypatch.setattr(os, "fsync", sync)
    runner = Runner(output_dir=output, agent_factory=ObservedAgent)
    if boundary in {"source", "source_directory"}:
        with pytest.raises(OSError, match="storage sync"):
            await runner.run(package)
    else:
        result = await runner.run(package)
        assert result.status == "failed" and not result.traces
    assert attempted and not generated
    assert all(not index.read_text() for index in output.glob("*/traces.jsonl"))


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["events", "snapshot"])
async def test_cancellation_survives_failed_terminal_persistence(
    tmp_path: Path, boundary: str
) -> None:
    from tests.test_runner import make_package

    output = tmp_path / "runs"
    waiting = asyncio.Event()
    finalized: list[bool] = []

    class WaitingAgent:
        async def generate(self, observation: Observation) -> Message:
            if not observation.messages:
                return Message("assistant", "durable")
            waiting.set()
            await asyncio.Future[None]()
            raise AssertionError("unreachable")

    class TwoTurns:
        async def setup(self, agents: Agents) -> None:
            pass

        async def run(self, task: TaskContext, agents: Agents) -> None:
            async with agents["assistant"].interaction(task) as interaction:
                await interaction.turn()
                await interaction.turn()

        async def finalize(self, task: TaskContext, trace: TraceSnapshot) -> None:
            finalized.append(True)

    running = asyncio.create_task(
        Runner(
            output_dir=output,
            agent_factory=lambda _: WaitingAgent(),
            environment_factory=lambda _: TwoTurns(),
        ).run(make_package(tmp_path / "task"))
    )
    await asyncio.wait_for(waiting.wait(), 2)
    trace_path = next(output.glob("*/traces/*"))
    target = trace_path / ("events.jsonl" if boundary == "events" else "trace.json")
    target.unlink(missing_ok=True)
    target.mkdir()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert finalized == [True]
    manifest = json.loads((trace_path.parent.parent / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    if boundary == "events":
        trace = load_trace(trace_path)
        assert trace.status == "failed"
        assert trace.conversation[0].message.content == "durable"
        assert any(event.kind == "agent_error" for event in trace.events)
    else:
        assert not (trace_path.parent.parent / "traces.jsonl").read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[], None, "not a Message"])
async def test_invalid_action_shapes_are_classified_as_malformed(
    tmp_path: Path, bad: object
) -> None:
    from tests.test_runner import make_package

    class InvalidAgent:
        async def generate(self, observation: Observation) -> Message | list[Message]:
            return cast(Message | list[Message], bad)

    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: InvalidAgent()
    ).run(make_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "agent_malformed" and not trace.conversation


@pytest.mark.asyncio
async def test_model_metadata_scrubs_configured_secret_keys_and_header_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentinstruct.providers import (
        ProviderCapabilities,
        ProviderRequest,
        ProviderResponse,
        SurfaceCapabilities,
    )

    secret = "metadata-runtime-secret"
    monkeypatch.setenv("PROVIDER_TEST_KEY", secret)

    class MetadataProvider:
        capabilities = ProviderCapabilities({"chat_completions": SurfaceCapabilities()})

        async def generate(self, request: ProviderRequest) -> ProviderResponse:
            return ProviderResponse(
                Message("assistant", "safe"),
                "stop",
                "test",
                request.model,
                metadata={
                    secret: "value",
                    "Authorization": "Bearer unknown-header-secret",
                },
            )

        async def aclose(self) -> None:
            pass

    result = await Runner(
        output_dir=tmp_path / "runs", provider_factory=lambda _: MetadataProvider()
    ).run(model_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    persisted = b"".join(p.read_bytes() for p in result.path.rglob("*") if p.is_file())
    assert (
        secret.encode() not in persisted and b"unknown-header-secret" not in persisted
    )
    assert b"[REDACTED]" in persisted


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_secret_seed_identity_matches_safe_snapshot_and_run_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, valid: bool
) -> None:
    from agentinstruct import Seed, SeedOrigin
    from tests.test_runner import GreetingAgent, make_package

    secret = "explicit-secret-seed-id"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=GreetingAgent
    ).run(
        make_package(tmp_path / "task"),
        seeds=[
            Seed(
                secret,
                {"id": "case", "name": "Ada"} if valid else {"id": "case"},
                SeedOrigin("python:seeds", 1, "python"),
                "",
            )
        ],
    )
    assert result.traces[0].seed_id == "[REDACTED]"
    run = load_run(result.path)
    assert run.traces[0].snapshot.seed_id == result.traces[0].seed_id
    assert result.traces[0].status == ("unverified" if valid else "invalid")
    persisted = b"".join(p.read_bytes() for p in result.path.rglob("*") if p.is_file())
    assert secret.encode() not in persisted
    assert secret not in json.dumps(result.to_dict())


@pytest.mark.asyncio
async def test_queued_message_starts_a_fresh_revision_budget(tmp_path: Path) -> None:
    from agentinstruct import ReviewRequest, ReviewResult
    from tests.test_review import make_review_package

    class RevisingAgent:
        async def generate(self, observation: Observation) -> Message | list[Message]:
            if observation.review_feedback is None:
                return Message("assistant", "reject")
            return [Message("assistant", "accept"), Message("assistant", "next")]

    class Reviewer:
        async def review(self, request: ReviewRequest) -> ReviewResult:
            if request.message.content == "next":
                raise RuntimeError("second independent subject failed")
            passed = request.message.content == "accept"
            return ReviewResult({"clear": passed, "complete": passed}, "Revise")

    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: RevisingAgent(),
        reviewer_factory=lambda _: Reviewer(),
    ).run(make_review_package(tmp_path / "task", policy="max_revisions = 1"))
    trace = load_trace(result.traces[0].path)
    assert [item.message.content for item in trace.conversation] == ["accept"]
    error = next(event for event in trace.events if event.kind == "review_error")
    assert error.data["revision"] == 0 and error.data["proposal_attempt"] == 2


@pytest.mark.asyncio
async def test_verifier_failure_keeps_safe_chained_cause_and_prior_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "verifier-runtime-secret"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    result = await Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    ).run(verified_package(tmp_path / "task"))

    class FailedVerifier:
        async def verify(self, trace: TraceSnapshot) -> VerificationResult:
            try:
                raise ValueError(secret)
            except ValueError as exc:
                raise RuntimeError("Authorization: Bearer unconfigured-secret") from exc

    attempt = await reverify(
        result.traces[0].path, verifier_factory=lambda _: FailedVerifier()
    )
    assert attempt.status == "unverified" and attempt.error is not None
    assert attempt.error.causes[0]["exception"] == "ValueError"
    assert attempt.events[0].data["stage"] == "verifier"
    assert load_trace(result.traces[0].path).status == "accepted"
    persisted = b"".join(p.read_bytes() for p in result.path.rglob("*") if p.is_file())
    assert secret.encode() not in persisted and b"unconfigured-secret" not in persisted


@pytest.mark.asyncio
async def test_review_approves_exact_redacted_content_and_executed_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Mapping

    from agentinstruct import ReviewRequest, ReviewResult, ToolContext
    from agentinstruct.plans import FrozenJsonValue, JsonValue
    from tests.test_tools import add_tool_review

    secret = "reviewed-runtime-secret"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    output = tmp_path / "runs"
    reviewed: list[Message] = []
    executed: list[object] = []

    class SecretAgent:
        async def generate(self, observation: Observation) -> Message:
            if observation.messages:
                return Message("assistant", "Reply " + secret)
            return Message(
                "assistant",
                "Proposal " + secret,
                tool_calls=(
                    ToolCall("lookup", FunctionCall("lookup", {"label": secret})),
                ),
            )

    class Reviewer:
        async def review(self, request: ReviewRequest) -> ReviewResult:
            reviewed.append(request.message)
            return ReviewResult({"allowed": True})

    class ObservedTool(LookupTool):
        async def call(
            self, args: Mapping[str, FrozenJsonValue], context: ToolContext
        ) -> JsonValue:
            executed.append(args["label"])
            return await super().call(args, context)

    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: SecretAgent(),
        reviewer_factory=lambda _: Reviewer(),
        tool_factory=lambda plan: ObservedTool(plan, output),
    ).run(add_tool_review(make_tool_package(tmp_path / "task")))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert reviewed == [
        commit.message
        for commit in trace.conversation
        if commit.message.role == "assistant"
    ]
    assert reviewed[0].content == "Proposal [REDACTED]"
    assert (
        executed
        == [reviewed[0].tool_calls[0].function.arguments["label"]]
        == ["[REDACTED]"]
    )
    assert reviewed[-1].content == "Reply [REDACTED]"


@pytest.mark.asyncio
async def test_redacted_tool_result_must_satisfy_output_schema_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Mapping

    from agentinstruct import TaskPackage, ToolContext
    from agentinstruct.plans import FrozenJsonValue, JsonValue
    from tests.test_tools import LookupAgent

    monkeypatch.setenv("OPENAI_API_KEY", "private-result-secret")
    package = make_tool_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'value = { type = "string" }',
            'value = { type = "string", pattern = "^private-" }',
        )
    )
    output = tmp_path / "runs"
    executed: list[bool] = []

    class SecretResultTool(LookupTool):
        async def call(
            self, args: Mapping[str, FrozenJsonValue], context: ToolContext
        ) -> JsonValue:
            executed.append(True)
            result = await super().call(args, context)
            assert isinstance(result, dict)
            result["value"] = "private-result-secret"
            return result

    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: SecretResultTool(plan, output),
    ).run(TaskPackage.load(package.root))
    trace = load_trace(result.traces[0].path)
    assert executed == [True]
    assert trace.generation.reason == "tool_result" and trace.status == "failed"
    assert len(trace.conversation) == 1 and trace.conversation[0].message.tool_calls
    assert any(event.kind == "tool_error" for event in trace.events)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    [
        "{'Authorization': 'Bearer unknown-secret with spaces'}",
        '{"X-Api-Key": "unknown-secret with spaces"}',
        "Authorization: 'Basic unknown-secret with spaces'",
        '{"Proxy-Authorization": "Bearer escaped\\"unknown-secret"}',
    ],
)
async def test_quoted_diagnostic_headers_are_scrubbed_in_errors_and_causes(
    tmp_path: Path, header: str
) -> None:
    from tests.test_runner import make_package

    class FailingAgent:
        async def generate(self, observation: Observation) -> Message:
            try:
                raise ValueError("Cause " + header)
            except ValueError as exc:
                raise RuntimeError("Outer " + header) from exc

    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: FailingAgent()
    ).run(make_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    failure = next(event for event in trace.events if event.kind == "agent_error")
    assert "[REDACTED]" in str(failure.data["message"])
    assert "[REDACTED]" in str(failure.data["causes"])
    persisted = b"".join(p.read_bytes() for p in result.path.rglob("*") if p.is_file())
    assert b"unknown-secret" not in persisted and b"with spaces" not in persisted
