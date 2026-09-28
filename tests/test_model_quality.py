"""Model quality gates through Runner and persisted sealed Trace evidence."""

import json
from pathlib import Path

import pytest

from agentinstruct import Runner, TaskPackage, load_trace
from agentinstruct.plans import canonical_json
from agentinstruct.providers import ChatCompletionsProvider
from tests.test_providers import FakeTransport, completion
from tests.test_review import make_review_package


def quality_package(root: Path) -> TaskPackage:
    make_review_package(root, policy="max_revisions = 0")
    task = root / "task.toml"
    task.write_text(
        task.read_text()
        .replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://test.example/v1"',
        )
        .replace('type = "custom"', 'type = "model"')
    )
    return TaskPackage.load(root)


@pytest.mark.asyncio
async def test_model_reviewer_scores_typed_verdicts_before_message_commit(
    tmp_path: Path,
) -> None:
    package = quality_package(tmp_path / "task")
    transport = FakeTransport(
        completion("proposal"),
        completion(
            '{"criteria":[{"id":"clear","passed":true},'
            '{"id":"complete","passed":false}],"feedback":"fine"}'
        ),
        completion("reply"),
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert [item.message.content for item in trace.conversation] == [
        "proposal",
        "reply",
    ]
    reviewer = json.loads(canonical_json(trace.run_plan))["agents"]["user"]["reviewer"]
    assert reviewer["structured_output"]["qualified_type"].endswith(":QualityDecision")
    assert len(reviewer["structured_output"]["fingerprint"]) == 64
    request = json.loads(transport.requests[1].content)
    assert request["response_format"]["type"] == "json_schema"
    assert transport.closed


@pytest.mark.asyncio
async def test_model_verifier_sidecars_preserve_generation_and_last_valid_decision(
    tmp_path: Path,
) -> None:
    from agentinstruct import reverify
    from tests.test_verification import verified_package

    root = tmp_path / "task"
    verified_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text()
        .replace('type = "custom"', 'type = "model"')
        .replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://test.example/v1"',
        )
    )
    (root / "verifier/instruction.md").write_text("Verify the response for {{ name }}.")
    preflight = FakeTransport()
    judge = FakeTransport(
        completion(
            '{"criteria":[{"id":"helpful","passed":true},'
            '{"id":"concise","passed":false}],"feedback":"Valid decision"}'
        )
    )
    transports = iter((preflight, judge))
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=next(transports)
        ),
    ).run(TaskPackage.load(root))
    path = result.traces[0].path
    trace = load_trace(path)
    assert trace.status == "accepted" and trace.verification[0].score == 0.75
    assert trace.verification[0].events[0].data["purpose"] == "verifier"
    assert preflight.closed and judge.closed
    generation = {p: p.read_bytes() for p in path.iterdir() if p.is_file()}
    broken = FakeTransport(
        completion(
            '{"criteria":[{"id":"helpful","passed":"true"},'
            '{"id":"concise","passed":false}],"feedback":"unsafe"}'
        )
    )
    attempt = await reverify(
        path,
        provider_factory=lambda plan: ChatCompletionsProvider(plan, transport=broken),
    )
    assert attempt.status == "unverified" and attempt.score is None
    assert (
        attempt.error is not None and attempt.error.provider_kind == "schema_mismatch"
    )
    assert (
        json.loads(canonical_json(attempt.events[0].data))["error"]["kind"]
        == "schema_mismatch"
    )
    assert load_trace(path).status == "accepted"
    assert broken.closed
    assert all(p.read_bytes() == data for p, data in generation.items())


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_call", [False, True])
@pytest.mark.parametrize(
    ("decision", "kind"),
    [
        (
            '{"criteria":[{"id":"clear","passed":1},'
            '{"id":"complete","passed":true}],"feedback":"bad"}',
            "schema_mismatch",
        ),
        (
            '{"criteria":[{"id":"clear","passed":true},'
            '{"id":"clear","passed":true},{"id":"complete","passed":true}],"feedback":"bad"}',
            "schema_mismatch",
        ),
        (
            '{"criteria":[{"id":"clear","passed":true}],"feedback":"bad"}',
            "schema_mismatch",
        ),
        (
            '{"criteria":[{"id":"clear","passed":true,"passed":false},'
            '{"id":"complete","passed":true}],"feedback":"bad"}',
            "invalid_json",
        ),
    ],
)
async def test_malformed_model_review_never_authorizes_message_or_tool(
    tmp_path: Path, tool_call: bool, decision: str, kind: str
) -> None:
    from tests.test_providers import wire_call
    from tests.test_tools import LookupTool, make_tool_package

    root = tmp_path / "task"
    if tool_call:
        make_tool_package(root)
        task = root / "task.toml"
        task.write_text(
            task.read_text().replace(
                'type = "openai"',
                'type = "openai-compatible"\nbase_url = "https://test.example/v1"',
            )
            + '\n[agents.assistant.reviewer]\ntype="model"\n'
            "accept_on_revision_exhaustion=true\n"
        )
        (root / "agents/assistant/reviewer.md").write_text("Check effects.")
        (root / "agents/assistant/rubric.toml").write_text(
            '[[criteria]]\nid="clear"\n[[criteria]]\nid="complete"\n'
        )
        package = TaskPackage.load(root)
    else:
        package = quality_package(root)
    transport = FakeTransport(
        wire_call() if tool_call else completion("proposal"), completion(decision)
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
        tool_factory=lambda plan: LookupTool(plan, tmp_path / "runs"),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and not trace.conversation
    assert len(transport.requests) == 2 and transport.closed
    evidence = next(
        event for event in trace.events if event.data.get("purpose") == "reviewer"
    )
    assert json.loads(canonical_json(evidence.data))["error"]["kind"] == kind
    assert evidence.turn_id and evidence.actor_id


@pytest.mark.asyncio
async def test_valid_negative_model_review_requests_revision_without_leaking_proposal(
    tmp_path: Path,
) -> None:
    root = tmp_path / "task"
    quality_package(root)
    task = root / "task.toml"
    task.write_text(task.read_text().replace("max_revisions = 0", "max_revisions = 1"))
    transport = FakeTransport(
        completion("rejected proposal"),
        completion(
            '{"criteria":[{"id":"clear","passed":false},'
            '{"id":"complete","passed":true}],"feedback":"Be clearer"}'
        ),
        completion("revised proposal"),
        completion(
            '{"criteria":[{"id":"clear","passed":true},'
            '{"id":"complete","passed":true}],"feedback":"good"}'
        ),
        completion("reply"),
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert [item.message.content for item in trace.conversation] == [
        "revised proposal",
        "reply",
    ]
    revision = json.loads(transport.requests[2].content)
    assert "Be clearer" in revision["messages"][-1]["content"]
    assert "rejected proposal" not in json.dumps(revision)
    assert "Be clearer" not in transport.requests[-1].content.decode()


@pytest.mark.asyncio
async def test_model_review_uses_current_step_criteria_with_one_stable_schema(
    tmp_path: Path,
) -> None:
    from tests.test_steps import SteppedAgent, step_package

    root = tmp_path / "task"
    step_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://test.example/v1"',
        )
        + '\n[agents.assistant.reviewer]\ntype="model"\n'
    )
    (root / "agents/assistant/reviewer.md").write_text("Check active criteria")
    (root / "agents/assistant/rubric.toml").write_text('[[criteria]]\nid="base"\n')
    for step in ("collect", "conclude"):
        (root / f"steps/{step}/agents/assistant/rubric.toml").write_text(
            f'[[criteria]]\nid="{step}"\n'
        )
    responses = [
        completion(
            json.dumps(
                {
                    "criteria": [
                        {"id": "base", "passed": True},
                        {"id": step, "passed": True},
                    ],
                    "feedback": "fine",
                }
            )
        )
        for step in ("collect", "collect", "conclude", "conclude")
    ]
    transport = FakeTransport(*responses)
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: SteppedAgent(),
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    requests = [json.loads(item.content) for item in transport.requests]
    assert len(requests) == 4
    assert all(
        item["response_format"] == requests[0]["response_format"] for item in requests
    )
    assert [
        {
            item["id"]
            for item in json.loads(request["messages"][1]["content"])["rubric"][
                "criteria"
            ]
        }
        for request in requests
    ] == [
        {"base", "collect"},
        {"base", "collect"},
        {"base", "conclude"},
        {"base", "conclude"},
    ]
    assert [
        event.step_id
        for event in trace.events
        if event.data.get("purpose") == "reviewer"
    ] == ["collect", "collect", "conclude", "conclude"]


@pytest.mark.asyncio
@pytest.mark.parametrize("component", ["reviewer", "verifier"])
async def test_all_quality_capabilities_are_checked_before_participant_inference(
    tmp_path: Path, component: str
) -> None:
    from agentinstruct.providers import ProviderCapabilities, SurfaceCapabilities
    from tests.test_runner import make_package

    class NoStructuredProvider(ChatCompletionsProvider):
        @property
        def capabilities(self) -> ProviderCapabilities:
            return ProviderCapabilities(
                {
                    "chat_completions": SurfaceCapabilities(
                        response_formats=frozenset({"text"})
                    )
                }
            )

    root = tmp_path / "task"
    make_package(root)
    task = root / "task.toml"
    text = task.read_text().replace(
        'type = "openai"',
        'type = "openai-compatible"\nbase_url = "https://test.example/v1"',
    )
    text += '\n[providers.judge]\ntype="openai-compatible"\nbase_url="https://judge.example/v1"\n'
    if component == "reviewer":
        text += (
            '\n[agents.assistant.reviewer]\ntype="model"\n'
            '[agents.assistant.reviewer.model]\nprovider="judge"\n'
        )
        (root / "agents/assistant/reviewer.md").write_text("Review")
        rubric = root / "agents/assistant/rubric.toml"
    else:
        text += '\n[verifier]\ntype="model"\n[verifier.model]\nprovider="judge"\n'
        (root / "verifier").mkdir()
        (root / "verifier/instruction.md").write_text("Verify")
        rubric = root / "verifier/rubric.toml"
    rubric.write_text('[[criteria]]\nid="valid"\n')
    task.write_text(text)
    transports: list[FakeTransport] = []
    from agentinstruct.plans import ProviderPlan

    def factory(plan: ProviderPlan) -> ChatCompletionsProvider:
        transport = FakeTransport()
        transports.append(transport)
        return (
            NoStructuredProvider if plan.id == "judge" else ChatCompletionsProvider
        )(plan, transport=transport)

    result = await Runner(output_dir=tmp_path / "runs", provider_factory=factory).run(
        TaskPackage.load(root)
    )
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and not trace.conversation
    assert trace.generation.reason == "provider_unsupported_feature"
    assert all(not transport.requests and transport.closed for transport in transports)


@pytest.mark.asyncio
async def test_verifier_timeout_closes_resource_and_records_sidecar_evidence(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from agentinstruct import reverify
    from tests.test_providers import SlowTransport
    from tests.test_verification import verified_package

    root = tmp_path / "task"
    verified_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text()
        .replace('type = "custom"', 'type = "model"')
        .replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://test.example/v1"',
        )
    )
    (root / "verifier/instruction.md").write_text("Verify {{ name }}")
    package = TaskPackage.load(root)
    preflight, transport = FakeTransport(), SlowTransport()
    transports = iter((preflight, transport))
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=next(transports)
        ),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    attempt = trace.verification[0]
    assert attempt.error is not None and attempt.error.kind == "timeout"
    assert (
        json.loads(canonical_json(attempt.events[0].data))["error"]["kind"] == "timeout"
    )
    assert preflight.closed and transport.closed
    # A valid negative decision rejects independently of the prior judge error.
    negative = FakeTransport(
        completion(
            '{"criteria":[{"id":"helpful","passed":false},{"id":"concise","passed":false}],"feedback":"No"}'
        )
    )
    attempt = await reverify(
        result.traces[0].path,
        plan=replace(attempt.plan, timeout_seconds=1),
        provider_factory=lambda plan: ChatCompletionsProvider(plan, transport=negative),
    )
    assert (
        attempt.status == "rejected" and attempt.score == 0.0 and attempt.error is None
    )
    assert negative.closed


@pytest.mark.asyncio
async def test_reverification_binds_persisted_seed_and_snapshots_changed_endpoint(
    tmp_path: Path,
) -> None:
    from agentinstruct import export_native, reverify
    from tests.test_verification import MixedJudge, verified_package

    root = tmp_path / "task"
    result = await Runner(
        output_dir=tmp_path / "runs", verifier_factory=lambda _: MixedJudge()
    ).run(verified_package(root))
    path = tmp_path / "exported.json"
    export_native([result.traces[0].path], path)
    original = path.read_bytes()
    task = root / "task.toml"
    task.write_text(
        task.read_text()
        .replace('type = "custom"', 'type = "model"')
        .replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://new-judge.example/v1"',
        )
    )
    (root / "verifier/instruction.md").write_text("Verify the answer for {{ name }}.")
    # The authoring package now has a different Seed; the sealed Trace owns the input.
    (root / "seed.json").write_text('{"name":"Different"}')
    transport = FakeTransport(
        completion(
            '{"criteria":[{"id":"helpful","passed":true},{"id":"concise","passed":true}],"feedback":"Yes"}'
        )
    )
    attempt = await reverify(
        path,
        package=TaskPackage.load(root),
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    )
    assert attempt.status == "accepted"
    assert attempt.plan.instruction == "Verify the answer for Ada."
    assert (
        attempt.provider is not None
        and attempt.provider.base_url == "https://new-judge.example/v1"
    )
    assert json.loads(transport.requests[0].content)["messages"][0][
        "content"
    ].startswith("Verify the answer for Ada.")
    assert path.read_bytes() == original
    assert path.with_name(path.name + ".verification").is_dir()
    assert load_trace(path).verification[-1].provider == attempt.provider
