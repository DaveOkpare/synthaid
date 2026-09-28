"""vLLM semantic contract through public Provider and Runner boundaries."""

import json
from pathlib import Path

import pytest

from agentinstruct import Message
from agentinstruct.plans import ProviderPlan, VllmOptions, VllmProfile, VllmSurface
from agentinstruct.providers import ProviderRequest
from agentinstruct.vllm import VllmProvider
from tests.test_providers import FakeTransport, completion


def profile(*, surfaces: dict[str, VllmSurface] | None = None) -> VllmProfile:
    return VllmProfile(
        vllm_version="0.30.0",
        model="test-model",
        model_revision="fixed-revision",
        chat_template="tokenizer_config.json@fixed-revision",
        server_flags=("--enable-auto-tool-choice",),
        hardware="test CPU transport; no compatibility claim",
        request_profile="contract-v1",
        surfaces=surfaces
        if surfaces is not None
        else {"chat_completions": VllmSurface()},
    )


@pytest.mark.asyncio
async def test_vllm_text_uses_chat_by_default_and_closes_transport() -> None:
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(),
        vllm_options=VllmOptions(),
    )
    transport = FakeTransport(completion())
    provider = VllmProvider(plan, transport=transport)
    result = await provider.generate(
        ProviderRequest("test-model", (Message("user", "Hi"),))
    )
    await provider.aclose()
    assert result.message.content == "Hello Ada."
    assert str(transport.requests[0].url) == "http://test/v1/chat/completions"
    assert json.loads(transport.requests[0].content)["store"] is False
    assert transport.closed
    assert provider.capabilities.surfaces["chat_completions"].response_formats == {
        "text"
    }
    assert "responses" not in provider.capabilities.surfaces


@pytest.mark.asyncio
async def test_native_options_and_reasoning_are_typed_private_and_profile_gated() -> (
    None
):
    from dataclasses import replace

    from agentinstruct.plans import VllmChatTemplateKwargs, VllmStructuredOutputs
    from agentinstruct.providers import ProviderError

    surface = VllmSurface(
        native_modes=("regex",),
        reasoning=True,
        reasoning_controls=(
            "enable_thinking",
            "thinking_token_budget",
            "include_reasoning",
        ),
        combinations=("native:regex+reasoning",),
    )
    options = VllmOptions(
        structured_outputs=VllmStructuredOutputs(regex="yes|no"),
        thinking_token_budget=128,
        include_reasoning=True,
        chat_template_kwargs=VllmChatTemplateKwargs(enable_thinking=True),
    )
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(surfaces={"chat_completions": surface}),
        vllm_options=options,
    )
    raw = completion("yes").json()
    raw["choices"][0]["message"]["reasoning"] = "Private thought."
    import httpx

    transport = FakeTransport(httpx.Response(200, json=raw))
    provider = VllmProvider(plan, transport=transport)
    result = await provider.generate(
        ProviderRequest("test-model", (Message("user", "Yes or no?"),))
    )
    assert result.message.content == "yes"
    assert result.reasoning[0].text == ("Private thought.",)
    body = json.loads(transport.requests[0].content)
    assert body["structured_outputs"] == {"regex": "yes|no"}
    assert body["thinking_token_budget"] == 128
    assert body["chat_template_kwargs"] == {"enable_thinking": True}
    assert body["include_reasoning"] is True
    await provider.aclose()
    unsupported = VllmProvider(
        replace(
            plan,
            vllm_profile=profile(
                surfaces={
                    "chat_completions": replace(surface, combinations=()),
                }
            ),
        )
    )
    with pytest.raises(ProviderError, match="unsupported_feature"):
        unsupported.capabilities.require(
            "chat_completions", ProviderRequest("test-model", (Message("user", "Hi"),))
        )
    with pytest.raises(ProviderError, match="unsupported_feature"):
        provider.capabilities.require(
            "chat_completions",
            ProviderRequest("another-model", (Message("user", "Hi"),)),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("retain", [True, False])
async def test_runner_persists_profile_and_keeps_reasoning_out_of_tool_continuation(
    tmp_path: Path,
    retain: bool,
) -> None:
    import httpx

    from agentinstruct import Runner, TaskPackage, export_openai, load_trace
    from agentinstruct.plans import canonical_json
    from tests.test_tools import LookupTool, make_tool_package

    root = tmp_path / "task"
    make_tool_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            """type = "vllm"
base_url = "http://test/v1"
[providers.default.vllm_profile]
vllm_version = "0.30.0"
model = "unused"
model_revision = "fixed-revision"
chat_template = "tokenizer_config.json@fixed-revision"
server_flags = [
  "--enable-auto-tool-choice", "--tool-call-parser", "hermes",
  "--reasoning-parser", "qwen3",
]
hardware = "deterministic transport"
request_profile = "contract-v1"
reasoning_parser = "qwen3"
tool_parser = "hermes"
[providers.default.vllm_profile.surfaces.chat_completions]
tool_choices = ["auto"]
reasoning = true
combinations = ["reasoning+tools"]
""",
        )
    )
    if not retain:
        task.write_text(
            task.read_text().replace(
                'type = "vllm"', 'type = "vllm"\nretain_reasoning = false'
            )
        )
    raw = completion("").json()
    raw["choices"][0]["finish_reason"] = "tool_calls"
    raw["choices"][0]["message"].update(
        {
            "reasoning": "Private: look up Ada.",
            "tool_calls": [
                {
                    "id": "lookup-1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"label":"Ada"}',
                    },
                }
            ],
        }
    )
    transport = FakeTransport(httpx.Response(200, json=raw), completion("Hello Ada."))
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        provider_factory=lambda plan: VllmProvider(plan, transport=transport),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert [item.message.role for item in trace.conversation] == [
        "assistant",
        "tool",
        "assistant",
    ]
    assert "Private:" not in canonical_json(trace.conversation)
    assert "Private:" not in transport.requests[1].content.decode()
    continuation = json.loads(transport.requests[1].content)["messages"]
    assert continuation[-1]["tool_call_id"] == "lookup-1"
    assert json.loads(continuation[-1]["content"])["durable"] is True
    assert ("Private:" in canonical_json(trace.events)) is retain
    call_event = next(event for event in trace.events if event.kind == "model_call")
    assert json.loads(canonical_json(call_event.data))["reasoning"]["returned"] is True
    assert (
        json.loads(canonical_json(call_event.data))["reasoning"]["retained"] is retain
    )
    persisted = json.loads(canonical_json(trace.run_plan))["providers"]["default"]
    assert persisted["api"] == "chat_completions"
    assert persisted["vllm_profile"]["model_revision"] == "fixed-revision"
    export_path = tmp_path / "training.jsonl"
    export_openai([result.traces[0].path], export_path, statuses={"unverified"})
    assert "Private:" not in export_path.read_text()
    assert transport.closed


@pytest.mark.asyncio
async def test_vllm_pydantic_round_trip_and_claimed_server_malformed_output() -> None:
    from pydantic import BaseModel

    from agentinstruct.providers import ProviderError

    class Answer(BaseModel):
        ok: bool

    surface = VllmSurface(response_formats=("text", "json_schema"))
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(surfaces={"chat_completions": surface}),
    )
    transport = FakeTransport(completion('{"ok":true}'), completion('{"ok":"true"}'))
    provider = VllmProvider(plan, transport=transport)
    request = ProviderRequest(
        "test-model", (Message("user", "Return an answer."),), structured_output=Answer
    )
    result = await provider.generate(request)
    assert isinstance(result.parsed, Answer) and result.parsed.ok is True
    assert (
        json.loads(transport.requests[0].content)["response_format"]["json_schema"][
            "strict"
        ]
        is True
    )
    with pytest.raises(ProviderError) as error:
        await provider.generate(request)
    assert error.value.kind == "schema_mismatch"
    await provider.aclose()


@pytest.mark.parametrize(
    "options",
    [
        {"thinking_token_budget": True},
        {"thinking_token_budget": 1.5},
        {"thinking_token_budget": -2},
        {"include_reasoning": "true"},
        {"guided_json": {}},
        {"extra_body": {}},
        {"chat_template_kwargs": {"unknown": True}},
        {"structured_outputs": {"regex": "yes", "choice": ["yes"]}},
        {"structured_outputs": {"structural_tag": {"type": "structural_tag"}}},
    ],
)
def test_vllm_rejects_untyped_or_removed_options(options: dict[str, object]) -> None:
    from pydantic import TypeAdapter, ValidationError

    with pytest.raises(ValidationError):
        TypeAdapter(VllmOptions).validate_json(json.dumps(options))


@pytest.mark.asyncio
async def test_responses_requires_separate_conformance_without_fallback() -> None:
    from dataclasses import replace

    from agentinstruct.providers import ProviderError
    from tests.test_responses import response

    plan = ProviderPlan(
        "local",
        "vllm",
        "responses",
        "http://test/v1",
        None,
        vllm_profile=profile(
            surfaces={
                "chat_completions": VllmSurface(
                    conformance="passed", report_digest="a" * 64
                ),
                "responses": VllmSurface(),
            }
        ),
    )
    with pytest.raises(ProviderError, match="unsupported_feature"):
        VllmProvider(plan)
    plan = replace(
        plan,
        vllm_profile=profile(
            surfaces={
                "responses": VllmSurface(conformance="passed", report_digest="b" * 64)
            }
        ),
    )
    transport = FakeTransport(response())
    provider = VllmProvider(plan, transport=transport)
    result = await provider.generate(
        ProviderRequest("test-model", (Message("user", "Hello"),))
    )
    assert result.message.content == "Hello Ada."
    assert transport.requests[0].url.path == "/v1/responses"
    await provider.aclose()


@pytest.mark.asyncio
async def test_conformance_covers_declared_modes_and_records_failures() -> None:
    from agentinstruct.vllm_conformance import conformance_cases, run_conformance

    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(
            surfaces={
                "chat_completions": VllmSurface(
                    response_formats=("text", "json_schema"),
                    native_modes=("regex",),
                )
            }
        ),
    )
    cases = conformance_cases(plan)
    assert {case.id for case in cases} == {"text", "json_schema", "native:regex"}
    transport = FakeTransport(
        completion("yes"), completion('{"answer":7}'), completion("incorrect")
    )
    report = await run_conformance(
        plan, provider_factory=lambda p: VllmProvider(p, transport=transport)
    )
    assert report["passed"] is False
    assert report["execution"] == "injected_transport"
    assert report["cases"] == [
        {"id": "text", "passed": True},
        {"id": "json_schema", "passed": True},
        {"id": "native:regex", "passed": False, "error": "semantic_mismatch"},
    ]
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("component", ["reviewer", "verifier"])
@pytest.mark.parametrize("mismatch", ["model", "combination"])
async def test_all_vllm_quality_requirements_preflight_before_inference(
    tmp_path: Path,
    component: str,
    mismatch: str,
) -> None:
    from agentinstruct import Runner, TaskPackage, load_trace
    from tests.test_runner import make_package

    root = tmp_path / "task"
    make_package(root)
    task = root / "task.toml"
    text = task.read_text().replace(
        'type = "openai"',
        """type = "vllm"
base_url = "http://test/v1"
[providers.default.vllm_profile]
vllm_version = "0.30.0"
model = "unused-model"
model_revision = "fixed"
chat_template = "fixed-template"
server_flags = []
hardware = "injected transport"
request_profile = "contract"
[providers.default.vllm_profile.surfaces.chat_completions]
response_formats = ["text", "json_schema"]
reasoning = true
""",
    )
    if component == "reviewer":
        text += '\n[agents.assistant.reviewer]\ntype="model"\n'
        if mismatch == "model":
            text += '[agents.assistant.reviewer.model]\nname="wrong-model"\n'
        (root / "agents/assistant/reviewer.md").write_text("Review")
        rubric = root / "agents/assistant/rubric.toml"
    else:
        text += '\n[verifier]\ntype="model"\n'
        if mismatch == "model":
            text += '[verifier.model]\nname="wrong-model"\n'
        (root / "verifier").mkdir()
        (root / "verifier/instruction.md").write_text("Verify")
        rubric = root / "verifier/rubric.toml"
    rubric.write_text('[[criteria]]\nid="valid"\n')
    task.write_text(text)
    transport = FakeTransport()
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: VllmProvider(plan, transport=transport),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and not trace.conversation
    assert trace.generation.reason == "provider_unsupported_feature"
    assert transport.closed and not transport.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,kind",
    [
        ("http", "unsupported_feature"),
        ("timeout", "timeout"),
        ("reasoning_shape", "malformed_response"),
        ("reasoning_tool_only", "malformed_response"),
        ("legacy_reasoning", "unsupported_feature"),
    ],
)
async def test_vllm_endpoint_contradictions_and_failures_are_typed(
    failure: str,
    kind: str,
) -> None:
    import httpx

    from agentinstruct.providers import ProviderError

    raw = completion("").json()
    if failure == "http":
        response: httpx.Response | Exception = httpx.Response(
            400, json={"error": {"code": "unsupported_feature"}}
        )
    elif failure == "timeout":
        response = httpx.ReadTimeout("unsafe transport detail")
    else:
        raw["choices"][0]["message"].update(
            {
                "reasoning_shape": {"reasoning": ["invalid"]},
                "reasoning_tool_only": {
                    "reasoning": '<tool_call>{"name":"lookup"}</tool_call>'
                },
                "legacy_reasoning": {"reasoning_content": "old alias"},
            }[failure]
        )
        response = httpx.Response(200, json=raw)
    transport = FakeTransport(response)
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(
            surfaces={"chat_completions": VllmSurface(reasoning=True)}
        ),
    )
    provider = VllmProvider(plan, transport=transport)
    with pytest.raises(ProviderError) as error:
        await provider.generate(ProviderRequest("test-model", (Message("user", "Hi"),)))
    assert error.value.kind == kind
    assert "unsafe" not in str(error.value)
    assert len(transport.requests) == 1
    await provider.aclose()


@pytest.mark.asyncio
async def test_generic_compatible_responses_uses_a_separate_portable_profile() -> None:
    from dataclasses import replace

    from agentinstruct import CompatibleEndpointProfile, CompatibleSurface
    from agentinstruct.providers import (
        ProviderError,
        ResponsesProvider,
        create_provider,
    )
    from tests.test_responses import response

    plan = ProviderPlan(
        "generic", "openai-compatible", "responses", "http://test/v1", None
    )
    with pytest.raises(ProviderError, match="unsupported_feature"):
        create_provider(plan)
    plan = replace(
        plan,
        endpoint_profile=CompatibleEndpointProfile(
            "test-model",
            "portable-responses-v1",
            {
                "responses": CompatibleSurface(
                    conformance="passed",
                    report_digest="c" * 64,
                )
            },
        ),
    )
    assert isinstance(create_provider(plan), ResponsesProvider)
    transport = FakeTransport(response())
    provider = ResponsesProvider(plan, transport=transport)
    result = await provider.generate(
        ProviderRequest("test-model", (Message("user", "Hi"),))
    )
    assert result.message.content == "Hello Ada."
    assert transport.requests[0].url.path == "/v1/responses"
    with pytest.raises(ProviderError, match="unsupported_feature"):
        provider.capabilities.require(
            "responses", ProviderRequest("different-model", (Message("user", "Hi"),))
        )
    assert "chat_completions" not in provider.capabilities.surfaces
    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["json", "choice", "regex", "grammar", "json_object", "structural_tag"]
)
async def test_every_native_mode_is_sent_through_typed_current_wire_options(
    mode: str,
) -> None:
    from typing import cast

    from agentinstruct.plans import VllmMode, VllmStructuredOutputs

    values = {
        "json": {
            "type": "object",
            "properties": {"answer": {"type": "integer"}, "empty": {"const": None}},
        },
        "choice": ["yes", "no"],
        "regex": "yes|no",
        "grammar": 'root ::= "yes"',
        "json_object": True,
        "structural_tag": '{"type":"structural_tag","structures":[],"triggers":[]}',
    }
    from pydantic import TypeAdapter

    native = TypeAdapter(VllmStructuredOutputs).validate_json(
        json.dumps({mode: values[mode]})
    )
    transport = FakeTransport(completion("yes"))
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(
            surfaces={
                "chat_completions": VllmSurface(native_modes=(cast(VllmMode, mode),))
            }
        ),
    )
    provider = VllmProvider(plan, transport=transport)
    await provider.generate(
        ProviderRequest(
            "test-model",
            (Message("user", "Answer"),),
            vllm_options=VllmOptions(structured_outputs=native),
        )
    )
    body = json.loads(transport.requests[0].content)
    assert body["structured_outputs"] == {mode: values[mode]}
    assert not any(key.startswith("guided_") for key in body)
    await provider.aclose()


@pytest.mark.parametrize(
    "flag",
    [
        "--api-key",
        "--api-key=secret",
        "--hf-token secret",
        "--auth-token",
        "--password",
    ],
)
def test_secret_launch_flags_cannot_enter_profile_provenance(flag: str) -> None:
    from dataclasses import replace

    with pytest.raises(ValueError, match="credentials"):
        replace(profile(), server_flags=(flag,))


def test_conformance_requires_explicit_opt_in_even_with_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentinstruct.vllm_conformance import main

    monkeypatch.setenv("VLLM_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://must-not-infer.invalid/v1")
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--profile",
                "conformance/vllm/qwen3-1.7b.json",
                "--hardware",
                "GPU",
                "--base-url",
                "http://must-not-infer.invalid/v1",
                "--output",
                str(tmp_path / "report.json"),
            ]
        )
    assert error.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_candidate_declares_only_cases_the_opt_in_harness_will_exercise() -> None:
    from agentinstruct.task_config import ProviderConfig
    from agentinstruct.vllm_conformance import conformance_cases

    config = json.loads(Path("conformance/vllm/qwen3-1.7b.json").read_text())
    config["base_url"] = "http://test/v1"
    candidate = ProviderConfig.model_validate(config)
    assert candidate.vllm_profile is not None
    plan = ProviderPlan(
        "candidate",
        "vllm",
        "chat_completions",
        candidate.base_url,
        None,
        vllm_profile=candidate.vllm_profile,
        vllm_options=candidate.vllm_options,
    )
    assert (
        candidate.vllm_profile.surfaces["chat_completions"].conformance == "unverified"
    )
    provider = VllmProvider(plan)
    cases = conformance_cases(plan)
    for case in cases:
        provider.capabilities.require(plan.api, case.request)
    names = {case.id for case in cases}
    assert {
        "reasoning+tools",
        "json_schema+reasoning",
        "json_object+reasoning",
        "native:regex+reasoning",
        "tools:auto",
        "tools:required",
        "tools:named",
        "tools:none",
        "control:enable_thinking",
        "control:include_reasoning",
        "control:thinking_token_budget",
    } <= names


def test_native_schema_and_profile_collections_are_immutable_snapshots() -> None:
    from agentinstruct import VllmStructuredOutputs
    from agentinstruct.plans import JsonValue, canonical_json

    schema: dict[str, JsonValue] = {"type": "object", "required": ["answer"]}
    native = VllmStructuredOutputs(json=schema)
    schema["required"] = []
    assert json.loads(canonical_json(native))["json"]["required"] == ["answer"]
    surfaces = {"chat_completions": VllmSurface()}
    snapshot = profile(surfaces=surfaces)
    surfaces.clear()
    assert "chat_completions" in snapshot.surfaces


def test_generic_profile_is_compiled_into_the_run_plan(tmp_path: Path) -> None:
    from agentinstruct import TaskPackage
    from agentinstruct.plans import canonical_json
    from tests.test_runner import make_package

    root = tmp_path / "task"
    make_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            """type = "openai-compatible"
api = "responses"
base_url = "http://test/v1"
[providers.default.endpoint_profile]
model = "unused-model"
request_profile = "portable-v1"
[providers.default.endpoint_profile.surfaces.responses]
response_formats = ["text", "json_schema"]
conformance = "passed"
report_digest = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
""",
        )
    )
    package = TaskPackage.load(root)
    stored = json.loads(canonical_json(package.compile().to_dict()))
    assert stored["providers"]["default"]["endpoint_profile"]["model"] == "unused-model"
    assert stored["providers"]["default"]["vllm_profile"] is None


@pytest.mark.asyncio
async def test_vllm_profile_survives_model_verification_and_reverification(
    tmp_path: Path,
) -> None:
    from agentinstruct import Runner, TaskPackage, load_trace, reverify
    from tests.test_runner import make_package

    root = tmp_path / "task"
    make_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            """type = "vllm"
base_url = "http://test/v1"
[providers.default.vllm_profile]
vllm_version = "0.30.0"
model = "unused-model"
model_revision = "fixed"
chat_template = "fixed-template"
server_flags = []
hardware = "injected transport"
request_profile = "quality-contract"
[providers.default.vllm_profile.surfaces.chat_completions]
response_formats = ["text", "json_schema"]
""",
        )
        + '\n[verifier]\ntype="model"\n'
    )
    (root / "verifier").mkdir()
    (root / "verifier/instruction.md").write_text("Verify the reply")
    (root / "verifier/rubric.toml").write_text('[[criteria]]\nid="valid"\n')
    generation = FakeTransport(completion("Hello Ada."))
    judge = FakeTransport(
        completion('{"criteria":[{"id":"valid","passed":true}],"feedback":""}')
    )
    transports = iter((generation, judge))
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: VllmProvider(plan, transport=next(transports)),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.status == "accepted"
    assert generation.closed and judge.closed
    later = FakeTransport(
        completion('{"criteria":[{"id":"valid","passed":false}],"feedback":""}')
    )
    attempt = await reverify(
        result.traces[0].path,
        provider_factory=lambda plan: VllmProvider(plan, transport=later),
    )
    assert attempt.status == "rejected"
    assert attempt.provider is not None and attempt.provider.vllm_profile is not None
    assert attempt.provider.vllm_profile.model_revision == "fixed"
    assert later.closed


@pytest.mark.asyncio
async def test_tool_response_contradicting_profile_is_typed() -> None:
    from agentinstruct.providers import ProviderError
    from tests.test_providers import wire_call

    transport = FakeTransport(wire_call())
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(),
    )
    provider = VllmProvider(plan, transport=transport)
    with pytest.raises(ProviderError) as error:
        await provider.generate(ProviderRequest("test-model", (Message("user", "Hi"),)))
    assert error.value.kind == "unsupported_feature"
    await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("output_kind", ["pydantic", "json_schema"])
async def test_structured_output_preserves_validation_with_inherited_native_defaults(
    output_kind: str,
) -> None:
    from pydantic import BaseModel

    from agentinstruct import JsonSchemaSpec
    from agentinstruct.providers import ResponseFormat

    class Answer(BaseModel):
        ok: bool

    surface = VllmSurface(
        response_formats=("text", "json_schema"),
        reasoning_controls=("include_reasoning",),
    )
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(surfaces={"chat_completions": surface}),
        vllm_options=VllmOptions(include_reasoning=False),
    )
    output = (
        Answer
        if output_kind == "pydantic"
        else JsonSchemaSpec(
            "Answer",
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
        )
    )
    request = ProviderRequest(
        "test-model",
        (Message("user", "Return an answer."),),
        structured_output=output,
    )
    transport = FakeTransport(completion('{"ok":true}'))
    provider = VllmProvider(plan, transport=transport)
    try:
        result = await provider.generate(request)
    finally:
        await provider.aclose()
    if output_kind == "pydantic":
        assert isinstance(result.parsed, Answer) and result.parsed.ok is True
    else:
        assert result.parsed == {"ok": True}
    body = json.loads(transport.requests[0].content)
    assert body["include_reasoning"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert request.vllm_options is None
    assert request.structured_output is output
    assert len(transport.requests) == 1 and transport.closed
    with pytest.raises(ValueError, match="Choose structured_output or response_format"):
        ProviderRequest(
            "test-model",
            request.messages,
            structured_output=output,
            response_format=ResponseFormat("json_object"),
        )


@pytest.mark.asyncio
async def test_reasoning_conformance_requires_evidence_with_suppressed_defaults() -> (
    None
):
    from agentinstruct.vllm_conformance import conformance_cases, run_conformance

    surface = VllmSurface(
        response_formats=("text", "json_schema"),
        reasoning=True,
        reasoning_controls=("include_reasoning", "enable_thinking"),
        combinations=("json_schema+reasoning",),
    )
    plan = ProviderPlan(
        "local",
        "vllm",
        "chat_completions",
        "http://test/v1",
        None,
        vllm_profile=profile(surfaces={"chat_completions": surface}),
        vllm_options=VllmOptions(include_reasoning=False),
    )
    cases = conformance_cases(plan)
    transport = FakeTransport(
        *(
            completion('{"answer":7}' if case.expected == "json" else "yes")
            for case in cases
        )
    )
    report = await run_conformance(
        plan,
        provider_factory=lambda p: VllmProvider(p, transport=transport),
    )
    assert report["passed"] is False
    assert report["cases"] == [
        {"id": "text", "passed": True},
        {"id": "json_schema", "passed": True},
        {"id": "reasoning", "passed": False, "error": "semantic_mismatch"},
        {"id": "json_schema+reasoning", "passed": False, "error": "semantic_mismatch"},
        {"id": "control:include_reasoning", "passed": True},
        {"id": "control:enable_thinking", "passed": True},
    ]
    requests = {
        case.id: json.loads(request.content)
        for case, request in zip(cases, transport.requests, strict=True)
    }
    assert requests["reasoning"]["include_reasoning"] is True
    assert requests["json_schema+reasoning"]["include_reasoning"] is True
    assert requests["control:include_reasoning"]["include_reasoning"] is False
    assert transport.closed
