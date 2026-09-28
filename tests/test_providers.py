"""Provider contract at its public semantic/HTTP boundary and the Runner seam."""

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest

from agentinstruct import (
    Message,
    Runner,
    TaskPackage,
    ToolPlan,
    export_native,
    export_openai,
    load_trace,
)
from agentinstruct.plans import FrozenJsonValue, ProviderPlan
from agentinstruct.providers import (
    ChatCompletionsProvider,
    InferenceControls,
    NamedToolChoice,
    ProviderCapabilities,
    ProviderError,
    ProviderRequest,
    ResponseFormat,
    SurfaceCapabilities,
)
from tests.test_dialogue import make_dialogue
from tests.test_review import WeightedReviewer, make_review_package
from tests.test_runner import make_package
from tests.test_steps import step_package
from tests.test_tools import LookupTool, make_tool_package


class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = iter(responses)
        self.requests: list[httpx.Request] = []
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        self.closed = True


def completion(content: str = "Hello Ada.") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chat-1",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        },
        headers={"x-request-id": "request-1"},
    )


def model_package(root: Path) -> TaskPackage:
    make_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            'type = "openai-compatible"\n'
            'base_url = "https://inference.example/v1"\n'
            'api_key_env = "PROVIDER_TEST_KEY"',
        )
    )
    return TaskPackage.load(root)


@pytest.mark.asyncio
async def test_model_generates_a_durable_trace_and_runner_closes_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = model_package(tmp_path / "task")
    monkeypatch.setenv("PROVIDER_TEST_KEY", "secret-provider-credential")
    transport = FakeTransport(completion())
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert trace.generation.state == "terminated"
    assert [item.message.content for item in trace.conversation] == ["Hello Ada."]
    call = next(event for event in trace.events if event.kind == "model_call")
    assert call.actor_id == "assistant"
    assert call.turn_id == trace.conversation[0].turn_id
    assert call.data["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
        "reasoning_tokens": None,
    }
    assert call.data["request_id"] == "request-1"
    assert isinstance(call.data["latency_seconds"], float)
    assert call.data["latency_seconds"] >= 0
    assert transport.closed
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert str(request.url) == "https://inference.example/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer secret-provider-credential"
    assert json.loads(request.content) == {
        "model": "unused-model",
        "messages": [{"role": "system", "content": "Greet Ada."}],
        "store": False,
        "stream": False,
        "n": 1,
    }
    exported = tmp_path / "dataset.jsonl"
    assert (
        export_native([result.traces[0].path], exported, statuses={"unverified"}) == 1
    )
    for path in result.path.rglob("*"):
        if path.is_file():
            assert b"secret-provider-credential" not in path.read_bytes()


def compatible_package(root: Path) -> TaskPackage:
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            'type = "openai-compatible"\nbase_url = "https://inference.example/v1"',
        )
    )
    return TaskPackage.load(root)


def wire_call(name: str = "lookup", *, identifier: str = "call-1") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chat-1",
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": identifier,
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": '{"label":"Ada"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    )


@pytest.mark.asyncio
async def test_provider_tool_intent_is_durable_before_effect_and_result_continuation(
    tmp_path: Path,
) -> None:
    root, output = tmp_path / "task", tmp_path / "runs"
    make_tool_package(root)
    transport = FakeTransport(wire_call(), completion("Result: Hello Ada"))
    result = await Runner(
        output_dir=output,
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(compatible_package(root))
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    call, tool_result, reply = trace.conversation
    assert call.message.tool_calls[0].function.arguments == {"label": "Ada"}
    assert json.loads(tool_result.message.content)["durable"] is True
    assert reply.message.content == "Result: Hello Ada"
    continued = json.loads(transport.requests[1].content)
    assert [item["role"] for item in continued["messages"]] == [
        "system",
        "assistant",
        "tool",
    ]
    assert (
        continued["messages"][1]["tool_calls"][0]["function"]["arguments"]
        == '{"label":"Ada"}'
    )
    assert continued["messages"][2]["tool_call_id"] == "call-1"
    assert transport.closed
    dataset = tmp_path / "data.jsonl"
    assert export_openai([result.traces[0].path], dataset, statuses={"unverified"}) == 1
    assert json.loads(dataset.read_text())["messages"][0]["tool_calls"][0]["function"][
        "arguments"
    ] == {"label": "Ada"}


@pytest.mark.asyncio
async def test_actor_projection_and_private_review_feedback_do_not_relay_drafts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "task"
    make_review_package(root)
    transport = FakeTransport(
        completion("rejected draft"), completion("revised reply"), completion("answer")
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
        reviewer_factory=lambda _: WeightedReviewer(),
    ).run(compatible_package(root))
    trace = load_trace(result.traces[0].path)
    assert [item.message.content for item in trace.conversation] == [
        "revised reply",
        "answer",
    ]
    requests = [json.loads(request.content) for request in transport.requests]
    assert requests[1]["messages"][-1] == {
        "role": "user",
        "content": (
            "Private review feedback for your next proposal:\n"
            "Review messages for Ada. Be clearer."
        ),
    }
    assert "rejected draft" not in json.dumps(requests)
    assert requests[2]["messages"] == [
        {"role": "system", "content": "You are assistant."},
        {"role": "user", "content": "revised reply"},
    ]
    assert [event.actor_id for event in trace.events if event.kind == "model_call"] == [
        "user",
        "user",
        "assistant",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        (401, None, "authentication"),
        (403, None, "authorization"),
        (429, None, "rate_limit"),
        (408, None, "timeout"),
        (400, None, "invalid_request"),
        (404, None, "invalid_request"),
        (404, "model_not_found", "model_unavailable"),
        (400, "unsupported_parameter", "unsupported_feature"),
        (500, None, "server"),
        (302, None, "unknown"),
    ],
)
async def test_http_failures_are_distinct_safe_not_retried_and_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    code: str | None,
    kind: str,
) -> None:
    monkeypatch.setenv("PROVIDER_TEST_KEY", "secret-provider-credential")
    transport = FakeTransport(
        httpx.Response(
            status,
            json={
                "error": {
                    "code": code,
                    "message": "secret-provider-credential",
                }
            },
            headers={
                "x-request-id": "request-secret-provider-credential",
                "authorization": "secret-provider-credential",
            },
        )
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(model_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == f"provider_{kind}"
    assert trace.status == "failed" and not trace.conversation
    event = next(event for event in trace.events if event.kind == "model_call")
    assert isinstance(event.data["error"], Mapping)
    assert event.data["error"]["kind"] == kind
    assert len(transport.requests) == 1 and transport.closed
    for path in result.path.rglob("*"):
        if path.is_file():
            assert b"secret-provider-credential" not in path.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (httpx.ReadTimeout("secret-provider-credential"), "timeout"),
        (httpx.ConnectError("secret-provider-credential"), "network"),
        (RuntimeError("secret-provider-credential"), "unknown"),
    ],
)
async def test_transport_failure_is_safe_and_has_no_hidden_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    kind: str,
) -> None:
    monkeypatch.setenv("PROVIDER_TEST_KEY", "secret-provider-credential")
    transport = FakeTransport(error)
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(model_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == f"provider_{kind}"
    assert len(transport.requests) == 1 and transport.closed
    assert "secret-provider-credential" not in str(trace)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem",
    [
        "bad_json",
        "boolean_usage",
        "multiple_choices",
        "malformed_arguments",
        "length_tools",
        "refusal_tools",
        "refusal",
        "length",
    ],
)
async def test_malformed_refused_or_incomplete_output_never_causes_effects(
    tmp_path: Path,
    problem: str,
) -> None:
    root = tmp_path / "task"
    make_tool_package(root)
    wire = completion().json()
    kind = "malformed_response"
    if problem == "boolean_usage":
        wire["usage"]["prompt_tokens"] = True
    elif problem == "multiple_choices":
        wire["choices"].append(wire["choices"][0])
    elif problem in {"malformed_arguments", "length_tools", "refusal_tools"}:
        wire = wire_call().json()
        if problem == "malformed_arguments":
            wire["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
                "[]"
            )
        elif problem == "length_tools":
            wire["choices"][0]["finish_reason"] = "length"
        else:
            wire["choices"][0]["message"]["refusal"] = "declined"
            kind = "refusal"
    elif problem == "refusal":
        wire["choices"][0]["message"]["refusal"] = "declined"
        kind = "refusal"
    elif problem == "length":
        wire["choices"][0]["finish_reason"] = "length"
        kind = "incomplete"
    response = (
        httpx.Response(200, content="not json")
        if problem == "bad_json"
        else httpx.Response(200, json=wire)
    )
    transport = FakeTransport(response)
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
        tool_factory=lambda plan: LookupTool(plan, tmp_path / "runs"),
    ).run(compatible_package(root))
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and not trace.conversation
    assert trace.generation.reason == f"provider_{kind}"
    assert transport.closed and len(transport.requests) == 1


class TextOnlyProvider(ChatCompletionsProvider):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            {"chat_completions": SurfaceCapabilities(function_tools=False)}
        )


@pytest.mark.asyncio
async def test_all_used_providers_are_preflighted_before_first_inference(
    tmp_path: Path,
) -> None:
    root = tmp_path / "task"
    make_dialogue(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text()
        + """
[providers.limited]
type = "openai-compatible"
base_url = "https://limited.example/v1"
[agents.assistant.model]
provider = "limited"
[tools.lookup]
description = "lookup"
[tools.lookup.input_schema]
type = "object"
"""
    )
    task.write_text(
        task.read_text().replace(
            "[agents.assistant]\ntarget = true",
            '[agents.assistant]\ntarget = true\ntools = ["lookup"]',
        )
    )
    transports = {name: FakeTransport() for name in ("default", "limited")}
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: (
            TextOnlyProvider if plan.id == "limited" else ChatCompletionsProvider
        )(plan, transport=transports[plan.id]),
    ).run(compatible_package(root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "provider_unsupported_feature"
    assert all(
        not transport.requests and transport.closed for transport in transports.values()
    )
    assert not trace.conversation


@pytest.mark.asyncio
async def test_openai_default_responses_is_rejected_without_silent_fallback(
    tmp_path: Path,
) -> None:
    result = await Runner(output_dir=tmp_path / "runs").run(
        make_package(tmp_path / "task")
    )
    assert (
        load_trace(result.traces[0].path).generation.reason
        == "provider_unsupported_feature"
    )


@pytest.mark.asyncio
async def test_scripted_task_never_constructs_unused_provider(tmp_path: Path) -> None:
    root = tmp_path / "task"
    make_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            "[agents.assistant]\ntarget = true",
            '[agents.assistant]\ntarget = true\ntype = "scripted"\n'
            'responses = ["offline"]',
        )
    )
    result = await Runner(output_dir=tmp_path / "runs").run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert [item.message.content for item in trace.conversation] == ["offline"]
    assert not any(item.kind.startswith("provider:") for item in trace.components)


class SlowTransport(FakeTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_runner_timeout_closes_inflight_provider(tmp_path: Path) -> None:
    root = tmp_path / "task"
    make_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "single"', 'type = "single"\ntimeout_seconds = 0.01'
        )
    )
    transport = SlowTransport()
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(compatible_package(root))
    trace = load_trace(result.traces[0].path)
    assert (
        trace.generation.state == "truncated" and trace.generation.reason == "timeout"
    )
    assert not trace.conversation
    assert transport.closed and len(transport.requests) == 1


@pytest.mark.asyncio
async def test_missing_runtime_credential_fails_without_inference_and_closes_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROVIDER_TEST_KEY", raising=False)
    transport = FakeTransport()
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(model_package(tmp_path / "task"))
    assert (
        load_trace(result.traces[0].path).generation.reason == "provider_authentication"
    )
    assert transport.closed and not transport.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["none", "auto", "required", "named"])
async def test_semantic_request_maps_tools_choice_formats_controls_and_immutable_input(
    choice: str,
) -> None:
    tool = ToolPlan("lookup", "Find a label", {"type": "object"})
    schema: dict[str, FrozenJsonValue] = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ("answer",),
        "additionalProperties": False,
    }
    response_format = ResponseFormat("json_schema", schema=schema)
    schema["properties"] = {"changed": True}
    transport = FakeTransport(completion('{"answer":"yes"}'))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    request = ProviderRequest(
        "model",
        (Message("system", "Reply"), Message("user", "Question")),
        (tool,),
        tool_choice=NamedToolChoice("lookup")
        if choice == "named"
        else cast(Literal["none", "auto", "required"], choice),
        parallel_tool_calls=False,
        response_format=response_format,
        inference=InferenceControls(temperature=0.5, max_tokens=32, top_p=0.8, seed=4),
        metadata={"trace_id": "trace-1"},
    )
    try:
        result = await provider.generate(request)
    finally:
        await provider.aclose()
    body = json.loads(transport.requests[0].content)
    assert body["tool_choice"] == (
        {"type": "function", "function": {"name": "lookup"}}
        if choice == "named"
        else choice
    )
    assert body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Find a label",
                "parameters": {"type": "object"},
            },
        }
    ]
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "result",
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
    assert body["max_completion_tokens"] == 32 and "max_tokens" not in body
    assert (body["temperature"], body["top_p"], body["seed"]) == (0.5, 0.8, 4)
    assert body["parallel_tool_calls"] is False
    assert result.message == Message("assistant", '{"answer":"yes"}')
    assert result.finish_state == "stop" and result.provider == "test"
    assert result.usage.total_tokens == 15
    assert result.metadata["response_id"] == "chat-1"
    assert transport.closed


@pytest.mark.asyncio
async def test_capability_rejection_is_model_free_at_public_provider_boundary() -> None:
    transport = FakeTransport()
    provider = TextOnlyProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    request = ProviderRequest(
        "model",
        (Message("user", "hello"),),
        (ToolPlan("lookup", "lookup", {}),),
        tool_choice="auto",
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(request)
        assert error.value.kind == "unsupported_feature"
    finally:
        await provider.aclose()
    assert not transport.requests and transport.closed


@pytest.mark.asyncio
async def test_response_echoes_cannot_persist_runtime_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "secret-provider-credential"
    monkeypatch.setenv("PROVIDER_TEST_KEY", secret)
    wire = completion(secret).json()
    wire["model"] = secret
    wire["system_fingerprint"] = secret
    wire["arbitrary_metadata"] = {"authorization": secret}
    transport = FakeTransport(
        httpx.Response(200, json=wire, headers={"x-request-id": secret})
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(model_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.conversation[0].message.content == "[REDACTED]"
    for path in result.path.rglob("*"):
        if path.is_file():
            assert secret.encode() not in path.read_bytes()


@pytest.mark.asyncio
async def test_model_steps_use_current_controls_and_keep_accepted_private_history(
    tmp_path: Path,
) -> None:
    root = tmp_path / "task"
    step_package(root)
    advance = wire_call("advance_step", identifier="advance").json()
    advance["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
        '{"step_id":"conclude"}'
    )
    complete = wire_call("complete_task", identifier="complete").json()
    complete["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "{}"
    transport = FakeTransport(
        completion("Collected Ada."),
        httpx.Response(200, json=advance),
        httpx.Response(200, json=complete),
        completion("Concluded Ada."),
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=transport
        ),
    ).run(compatible_package(root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated" and trace.status == "unverified"
    assert [item.step_id for item in trace.conversation] == [
        "collect",
        "collect",
        "collect",
        "conclude",
        "conclude",
        "conclude",
    ]
    requests = [json.loads(request.content) for request in transport.requests]
    assert [request["messages"][0]["content"] for request in requests] == [
        "Base Ada.\n\nCollect Ada.",
        "Base Ada.\n\nCollect Ada.",
        "Base Ada.\n\nConclude Ada.",
        "Base Ada.\n\nConclude Ada.",
    ]
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == [
        "advance_step"
    ]
    assert [tool["function"]["name"] for tool in requests[2]["tools"]] == [
        "complete_task"
    ]
    assert "tools" not in requests[3]
    assert [message["role"] for message in requests[3]["messages"]] == [
        "system",
        "assistant",
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    calls = [event for event in trace.events if event.kind == "model_call"]
    assert [event.step_id for event in calls] == [
        "collect",
        "collect",
        "conclude",
        "conclude",
    ]
    assert all(event.turn_id for event in calls)


@pytest.mark.asyncio
async def test_multiple_function_proposals_preserve_order_at_provider_boundary() -> (
    None
):
    wire = wire_call().json()
    wire["choices"][0]["message"]["tool_calls"].append(
        {
            "id": "call-2",
            "type": "function",
            "function": {"name": "second", "arguments": '{"nested":[1,2]}'},
        }
    )
    transport = FakeTransport(httpx.Response(200, json=wire))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        result = await provider.generate(
            ProviderRequest("model", (Message("user", "hello"),))
        )
    finally:
        await provider.aclose()
    assert [call.id for call in result.message.tool_calls] == ["call-1", "call-2"]
    assert result.message.tool_calls[1].function.arguments == {"nested": (1, 2)}
    assert result.finish_state == "tool_calls"


@pytest.mark.asyncio
async def test_json_encoded_tool_arguments_do_not_retain_escaped_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = 'credential-with-"quote'
    monkeypatch.setenv("PROVIDER_TEST_KEY", secret)
    wire = wire_call().json()
    wire["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
        json.dumps({"label": secret})
    )
    transport = FakeTransport(httpx.Response(200, json=wire))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            "PROVIDER_TEST_KEY",
        ),
        transport=transport,
    )
    try:
        result = await provider.generate(
            ProviderRequest("model", (Message("user", "hello"),))
        )
    finally:
        await provider.aclose()
    assert result.message.tool_calls[0].function.arguments == {"label": "[REDACTED]"}
