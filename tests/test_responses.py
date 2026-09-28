"""Responses semantic parity and private reasoning through public boundaries."""

import json
from pathlib import Path
from typing import Literal

import httpx
import pytest

from agentinstruct import Message, Runner, TaskPackage, load_trace
from agentinstruct.plans import ProviderPlan, canonical_json
from agentinstruct.providers import ProviderRequest, ResponsesProvider
from tests.test_providers import FakeTransport
from tests.test_runner import make_package


def response(
    content: str = "Hello Ada.", *, output: list[object] | None = None
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "resp-1",
            "model": "test-model",
            "status": "completed",
            "output": output
            if output is not None
            else [
                {
                    "type": "message",
                    "id": "msg-1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": content, "annotations": []}
                    ],
                }
            ],
            "usage": {
                "input_tokens": 12,
                "output_tokens": 3,
                "total_tokens": 15,
                "output_tokens_details": {"reasoning_tokens": 1},
            },
        },
        headers={"x-request-id": "request-1"},
    )


def responses_package(root: Path) -> TaskPackage:
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            'type = "openai"\nbase_url = "https://test.example/v1"\n'
            'api_key_env = "RESPONSES_TEST_KEY"',
        )
    )
    return TaskPackage.load(root)


@pytest.mark.asyncio
async def test_default_openai_responses_generates_durable_self_contained_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "task"
    make_package(root)
    package = responses_package(root)
    monkeypatch.setenv("RESPONSES_TEST_KEY", "test-secret")
    transport = FakeTransport(response())
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ResponsesProvider(plan, transport=transport),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert [item.message.content for item in trace.conversation] == ["Hello Ada."]
    assert (
        json.loads(canonical_json(trace.run_plan))["providers"]["default"]["api"]
        == "responses"
    )
    event = next(event for event in trace.events if event.kind == "model_call")
    assert json.loads(canonical_json(event.data))["usage"]["reasoning_tokens"] == 1
    assert json.loads(canonical_json(event.data))["metadata"]["response_id"] == "resp-1"
    assert json.loads(canonical_json(event.data))["metadata"]["output_item_ids"] == [
        "msg-1"
    ]
    assert str(transport.requests[0].url) == "https://test.example/v1/responses"
    assert json.loads(transport.requests[0].content) == {
        "model": "unused-model",
        "input": [{"role": "system", "content": "Greet Ada."}],
        "store": False,
        "stream": False,
    }
    assert transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        '{"checks":[{"passed":true,"label":"good","note":null}],"day":"2026-09-28"}',
        '{"checks":[{"passed":1,"label":"good","note":null}],"day":"2026-09-28"}',
        '{"checks":[],"day":"wrong"}',
        "not json",
        '{"checks":[],"checks":[],"day":"2026-09-28"}',
    ],
)
async def test_surfaces_produce_equal_typed_values_or_structured_errors(
    content: str,
) -> None:
    from agentinstruct import ChatCompletionsProvider, ProviderError
    from tests.test_providers import completion
    from tests.test_structured_output import Report

    outcomes: list[object] = []
    for api, adapter, wire in (
        ("responses", ResponsesProvider, response(content)),
        ("chat_completions", ChatCompletionsProvider, completion(content)),
    ):
        transport = FakeTransport(wire)
        provider = adapter(
            ProviderPlan(
                "test", "openai-compatible", api, "https://test.example/v1", None
            ),
            transport=transport,
        )
        try:
            result = await provider.generate(
                ProviderRequest(
                    "model", (Message("user", "Evaluate"),), structured_output=Report
                )
            )
            assert isinstance(result.parsed, Report)
            outcomes.append(result.parsed)
        except ProviderError as exc:
            outcomes.append(exc.kind)
        finally:
            await provider.aclose()
        body = json.loads(transport.requests[0].content)
        schema = (
            body["text"]["format"]
            if api == "responses"
            else body["response_format"]["json_schema"]
        )
        assert schema["name"] == "Report" and schema["strict"] is True
    assert outcomes[0] == outcomes[1]


def function_item(identifier: str = "call-1", label: str = "Ada") -> dict[str, object]:
    return {
        "type": "function_call",
        "id": "fc-" + identifier,
        "call_id": identifier,
        "name": "lookup",
        "arguments": json.dumps({"label": label}),
        "status": "completed",
    }


def reasoning_item(
    identifier: str = "reason-1", text: str = "Private summary"
) -> dict[str, object]:
    return {
        "type": "reasoning",
        "id": identifier,
        "summary": [{"type": "summary_text", "text": text}],
        "encrypted_content": "opaque-" + identifier,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("retain", [True, False])
async def test_accepted_tool_continuation_keeps_reasoning_private_and_honors_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retain: bool,
) -> None:
    from agentinstruct import export_openai
    from tests.test_tools import LookupTool, make_tool_package

    root, output = tmp_path / "task", tmp_path / "runs"
    make_tool_package(root)
    responses_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai"',
            f'type = "openai"\nretain_reasoning = {str(retain).lower()}',
        )
    )
    monkeypatch.setenv("RESPONSES_TEST_KEY", "test-secret")
    transport = FakeTransport(
        response(output=[reasoning_item(), function_item()]), response("Done.")
    )
    result = await Runner(
        output_dir=output,
        provider_factory=lambda plan: ResponsesProvider(plan, transport=transport),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(TaskPackage.load(root))
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert len(trace.conversation) == 3
    continued = json.loads(transport.requests[1].content)
    assert "previous_response_id" not in continued and continued["store"] is False
    assert [item.get("type", "message") for item in continued["input"]] == [
        "message",
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert continued["input"][1] == reasoning_item()
    assert (
        continued["input"][2]["call_id"] == continued["input"][3]["call_id"] == "call-1"
    )
    event = next(event for event in trace.events if event.kind == "model_call")
    evidence = json.loads(canonical_json(event.data))["reasoning"]
    assert evidence["returned"] is True and evidence["retained"] is retain
    assert ("Private summary" in canonical_json(trace)) is retain
    assert ("opaque-reason-1" in canonical_json(trace)) is retain
    assert "Private summary" not in canonical_json(trace.conversation)
    dataset = tmp_path / "train.jsonl"
    export_openai([result.traces[0].path], dataset, statuses={"unverified"})
    assert (
        "reason-1" not in dataset.read_text()
        and "Private summary" not in dataset.read_text()
    )


@pytest.mark.asyncio
async def test_rejected_reasoning_is_not_continued_and_other_actor_never_receives_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentinstruct import export_openai
    from tests.test_review import WeightedReviewer, make_review_package

    root = tmp_path / "task"
    make_review_package(root)
    package = responses_package(root)
    monkeypatch.setenv("RESPONSES_TEST_KEY", "test-secret")
    final = response("revised reply").json()["output"]
    transport = FakeTransport(
        response(
            output=[
                reasoning_item("rejected", "rejected reasoning"),
                *response("draft").json()["output"],
            ]
        ),
        response(output=[reasoning_item("accepted", "accepted reasoning"), *final]),
        response("answer"),
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ResponsesProvider(plan, transport=transport),
        reviewer_factory=lambda _: WeightedReviewer(),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert [item.message.content for item in trace.conversation] == [
        "revised reply",
        "answer",
    ]
    requests = [json.loads(item.content) for item in transport.requests]
    assert "rejected reasoning" not in json.dumps(requests)
    assert "accepted reasoning" not in json.dumps(requests)
    assert requests[2]["input"] == [
        {"role": "system", "content": "You are assistant."},
        {"role": "user", "content": "revised reply"},
    ]
    assert [event.actor_id for event in trace.events if event.kind == "model_call"] == [
        "user",
        "user",
        "assistant",
    ]
    dataset = tmp_path / "train.jsonl"
    export_openai([result.traces[0].path], dataset, statuses={"unverified"})
    assert "reasoning" not in dataset.read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state", ["refusal", "max_output_tokens", "content_filter", "failed", "queued"]
)
async def test_non_success_precedes_partial_tool_and_structured_parsing(
    state: str,
) -> None:
    from agentinstruct import ProviderError
    from tests.test_structured_output import Report

    broken_call = function_item()
    broken_call["arguments"] = '{"label":'
    payload = response(output=[reasoning_item(), broken_call]).json()
    if state == "refusal":
        payload["output"].insert(
            1,
            {
                "type": "message",
                "id": "refusal",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "Cannot comply"}],
            },
        )
    elif state in {"failed", "queued"}:
        payload["status"] = state
    else:
        payload["status"] = "incomplete"
        payload["incomplete_details"] = {"reason": state}
    transport = FakeTransport(httpx.Response(200, json=payload))
    provider = ResponsesProvider(
        ProviderPlan(
            "test", "openai-compatible", "responses", "https://test.example/v1", None
        ),
        transport=transport,
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(
                ProviderRequest(
                    "model", (Message("user", "Evaluate"),), structured_output=Report
                )
            )
        assert error.value.kind == (
            "refusal"
            if state == "refusal"
            else "server"
            if state == "failed"
            else "incomplete"
        )
    finally:
        await provider.aclose()
    assert len(transport.requests) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["none", "auto", "required", "named"])
async def test_ordered_function_calls_and_tool_choices_have_surface_parity(
    choice: Literal["none", "auto", "required", "named"],
) -> None:
    from agentinstruct import (
        ChatCompletionsProvider,
        FunctionCall,
        InferenceControls,
        NamedToolChoice,
        ToolCall,
        ToolPlan,
    )
    from tests.test_providers import wire_call

    history = (
        Message("system", "Use tools"),
        Message("user", "Find Ada"),
        Message(
            "assistant",
            "Looking up",
            tool_calls=(
                ToolCall("old-call", FunctionCall("lookup", {"label": "Ada"})),
            ),
        ),
        Message("tool", '{"found":true}', tool_call_id="old-call"),
    )
    tool = ToolPlan(
        "lookup",
        "Look up",
        {"type": "object", "properties": {"label": {"type": "string"}}},
    )
    request = ProviderRequest(
        "model",
        history,
        (tool,),
        tool_choice=NamedToolChoice("lookup") if choice == "named" else choice,
        parallel_tool_calls=True,
        inference=InferenceControls(temperature=0.4, top_p=0.8, max_tokens=100),
    )
    chat = wire_call().json()
    chat["choices"][0]["message"]["tool_calls"].append(
        {
            "id": "call-2",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"label":"Grace"}'},
        }
    )
    messages: list[object] = []
    for api, adapter, wire in (
        (
            "responses",
            ResponsesProvider,
            response(output=[function_item(), function_item("call-2", "Grace")]),
        ),
        ("chat_completions", ChatCompletionsProvider, httpx.Response(200, json=chat)),
    ):
        transport = FakeTransport(wire)
        provider = adapter(
            ProviderPlan(
                "test", "openai-compatible", api, "https://test.example/v1", None
            ),
            transport=transport,
        )
        try:
            result = await provider.generate(request)
        finally:
            await provider.aclose()
        assert result.finish_state == "tool_calls"
        messages.append(result.message)
        body = json.loads(transport.requests[0].content)
        assert body["parallel_tool_calls"] is True
        if api == "responses":
            assert body["input"] == [
                {"role": "system", "content": "Use tools"},
                {"role": "user", "content": "Find Ada"},
                {"role": "assistant", "content": "Looking up"},
                {
                    "type": "function_call",
                    "call_id": "old-call",
                    "name": "lookup",
                    "arguments": '{"label":"Ada"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "old-call",
                    "output": '{"found":true}',
                },
            ]
            assert (
                body["tools"][0]["type"] == "function"
                and body["tools"][0]["strict"] is False
            )
            assert body["tool_choice"] == (
                {"type": "function", "name": "lookup"} if choice == "named" else choice
            )
            assert body["max_output_tokens"] == 100
        else:
            assert body["tool_choice"] == (
                {"type": "function", "function": {"name": "lookup"}}
                if choice == "named"
                else choice
            )
            assert body["max_completion_tokens"] == 100
        assert body["temperature"] == 0.4 and body["top_p"] == 0.8
    assert messages[0] == messages[1]


@pytest.mark.asyncio
async def test_reasoning_controls_are_inherited_and_preflighted_before_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agentinstruct import ChatCompletionsProvider

    root = tmp_path / "task"
    make_package(root)
    responses_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'name = "unused-model"',
            'name = "unused-model"\nreasoning = { effort = "low", summary = "auto" }',
        )
    )
    package = TaskPackage.load(root)
    monkeypatch.setenv("RESPONSES_TEST_KEY", "test-secret")
    transport = FakeTransport(response())
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ResponsesProvider(plan, transport=transport),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert json.loads(transport.requests[0].content)["reasoning"] == {
        "effort": "low",
        "summary": "auto",
    }
    assert json.loads(canonical_json(trace.run_plan))["agents"]["assistant"]["model"][
        "reasoning"
    ] == {"effort": "low", "summary": "auto"}
    task.write_text(
        task.read_text().replace(
            'type = "openai"', 'type = "openai"\napi = "chat_completions"'
        )
    )
    incompatible = FakeTransport()
    failed = await Runner(
        output_dir=tmp_path / "unsupported",
        provider_factory=lambda plan: ChatCompletionsProvider(
            plan, transport=incompatible
        ),
    ).run(TaskPackage.load(root))
    assert (
        load_trace(failed.traces[0].path).generation.reason
        == "provider_unsupported_feature"
    )
    assert not incompatible.requests and incompatible.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output, kind",
    [
        (
            [{**function_item(), "arguments": '{"label":"Ada","label":"Grace"}'}],
            "malformed_response",
        ),
        ([function_item(), function_item()], "malformed_response"),
        (
            [{"type": "web_search_call", "id": "hosted-1", "status": "completed"}],
            "unsupported_feature",
        ),
        (
            [
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "untrusted",
                }
            ],
            "malformed_response",
        ),
    ],
)
async def test_malformed_and_hosted_tool_outputs_never_authorize_effects(
    output: list[object], kind: str
) -> None:
    from agentinstruct import ProviderError

    transport = FakeTransport(response(output=output))
    provider = ResponsesProvider(
        ProviderPlan(
            "test", "openai-compatible", "responses", "https://test.example/v1", None
        ),
        transport=transport,
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(ProviderRequest("model", (Message("user", "Act"),)))
        assert error.value.kind == kind
    finally:
        await provider.aclose()
    assert len(transport.requests) == 1 and transport.closed


@pytest.mark.asyncio
async def test_responses_quality_gates_record_private_reasoning_in_separate_attempts(
    tmp_path: Path,
) -> None:
    from agentinstruct import export_openai, reverify
    from tests.test_model_quality import quality_package

    root = tmp_path / "task"
    quality_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text().replace(
            'type = "openai-compatible"',
            'type = "openai-compatible"\napi = "responses"',
        )
    )
    task.write_text(task.read_text() + '\n[verifier]\ntype = "model"\n')
    (root / "verifier").mkdir()
    (root / "verifier/instruction.md").write_text("Judge the conversation.")
    (root / "verifier/rubric.toml").write_text(
        '[[criteria]]\nid = "clear"\n[[criteria]]\nid = "complete"\n'
    )
    verdict = (
        '{"criteria":[{"id":"clear","passed":true},'
        '{"id":"complete","passed":true}],"feedback":"Good"}'
    )
    transports = [
        FakeTransport(
            response("proposal"),
            response(
                output=[
                    reasoning_item("review", "review summary"),
                    *response(verdict).json()["output"],
                ]
            ),
            response("reply"),
        ),
        FakeTransport(
            response(
                output=[
                    reasoning_item("verify", "verify summary"),
                    *response(verdict).json()["output"],
                ]
            )
        ),
    ]
    pending = iter(transports)
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ResponsesProvider(plan, transport=next(pending)),
    ).run(TaskPackage.load(root))
    trace_path = result.traces[0].path
    trace = load_trace(trace_path)
    assert trace.status == "accepted"
    reviewer = next(
        event for event in trace.events if event.data.get("purpose") == "reviewer"
    )
    assert "review summary" in canonical_json(reviewer.data)
    assert "verify summary" not in canonical_json(trace.events)
    assert "verify summary" in canonical_json(trace.verification[0].events)
    generation = {
        path: path.read_bytes() for path in trace_path.iterdir() if path.is_file()
    }
    failed_transport = FakeTransport(
        response(
            output=[
                reasoning_item("bad-judge", "Invalid judge summary"),
                *response("bad JSON").json()["output"],
            ]
        )
    )
    attempt = await reverify(
        trace_path,
        provider_factory=lambda plan: ResponsesProvider(
            plan, transport=failed_transport
        ),
    )
    assert attempt.error is not None and attempt.error.provider_kind == "invalid_json"
    assert "Invalid judge summary" in canonical_json(attempt.events)
    assert all(path.read_bytes() == content for path, content in generation.items())
    assert load_trace(trace_path).status == "accepted"
    assert all(transport.closed for transport in [*transports, failed_transport])
    dataset = tmp_path / "train.jsonl"
    export_openai([trace_path], dataset)
    assert "summary" not in dataset.read_text()


@pytest.mark.asyncio
async def test_model_agent_only_promotes_reasoning_for_newly_accepted_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from agentinstruct import Observation
    from agentinstruct.model_agent import ModelAgent
    from tests.test_tools import make_tool_package

    root = tmp_path / "task"
    make_tool_package(root)
    plan = responses_package(root).compile()
    monkeypatch.setenv("RESPONSES_TEST_KEY", "test-secret")
    transport = FakeTransport(
        response(
            output=[reasoning_item("original", "accepted reasoning"), function_item()]
        ),
        response(
            output=[reasoning_item("rejected", "rejected reasoning"), function_item()]
        ),
        response("Revised final reply."),
    )
    provider = ResponsesProvider(plan.providers["default"], transport=transport)
    agent = ModelAgent(
        plan.agents["assistant"],
        plan.providers["default"],
        provider,
        record_event=lambda _: None,
        run_id="run",
        trace_id="trace",
    )
    try:
        proposal = await agent.generate(Observation("assistant", "Act.", ()))
        accepted = replace(proposal, id="accepted-message", actor_id="assistant")
        tool_result = Message(
            "tool",
            "Found Ada",
            id="result-message",
            actor_id="assistant",
            tool_call_id="call-1",
        )
        observation = Observation("assistant", "Act.", (accepted, tool_result))
        await agent.generate(observation)
        await agent.generate(
            replace(observation, review_feedback="Use existing result.")
        )
    finally:
        await provider.aclose()
    revision = json.loads(transport.requests[2].content)
    assert "accepted reasoning" in json.dumps(revision)
    assert "rejected reasoning" not in json.dumps(revision)
    assert revision["input"][1] == reasoning_item("original", "accepted reasoning")


@pytest.mark.asyncio
async def test_interleaved_reasoning_and_ordered_calls_keep_continuation_order() -> (
    None
):
    from agentinstruct import ReasoningContinuation

    transport = FakeTransport(
        response(
            output=[
                reasoning_item("first"),
                function_item(),
                reasoning_item("second"),
                function_item("call-2", "Grace"),
            ]
        ),
        response("Done."),
    )
    provider = ResponsesProvider(
        ProviderPlan(
            "test", "openai-compatible", "responses", "https://test.example/v1", None
        ),
        transport=transport,
    )
    try:
        initial = await provider.generate(
            ProviderRequest("model", (Message("user", "Act"),))
        )
        await provider.generate(
            ProviderRequest(
                "model",
                (
                    Message("user", "Act"),
                    initial.message,
                    Message("tool", "Ada", tool_call_id="call-1"),
                    Message("tool", "Grace", tool_call_id="call-2"),
                ),
                continuations=(
                    ReasoningContinuation(initial.message, initial.reasoning),
                ),
            )
        )
    finally:
        await provider.aclose()
    items = json.loads(transport.requests[1].content)["input"]
    assert [
        (item["type"], item.get("id", item.get("call_id"))) for item in items[1:]
    ] == [
        ("reasoning", "first"),
        ("function_call", "call-1"),
        ("reasoning", "second"),
        ("function_call", "call-2"),
        ("function_call_output", "call-1"),
        ("function_call_output", "call-2"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["refusal", "length"])
async def test_unstructured_partial_tool_states_have_semantic_parity(
    state: str,
) -> None:
    from agentinstruct import ChatCompletionsProvider
    from tests.test_providers import wire_call

    chat = wire_call().json()
    chat["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
        '{"label":'
    )
    broken = function_item()
    broken["arguments"] = '{"label":'
    responses = response(output=[broken]).json()
    if state == "refusal":
        chat["choices"][0]["message"]["refusal"] = "Declined"
        responses["output"].append(
            {
                "type": "message",
                "id": "refusal",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "Declined"}],
            }
        )
    else:
        chat["choices"][0]["finish_reason"] = "length"
        responses["status"] = "incomplete"
        responses["incomplete_details"] = {"reason": "max_output_tokens"}
    normalized: list[object] = []
    for api, adapter, payload in (
        ("responses", ResponsesProvider, responses),
        ("chat_completions", ChatCompletionsProvider, chat),
    ):
        provider = adapter(
            ProviderPlan(
                "test", "openai-compatible", api, "https://test.example/v1", None
            ),
            transport=FakeTransport(httpx.Response(200, json=payload)),
        )
        try:
            result = await provider.generate(
                ProviderRequest("model", (Message("user", "Act"),))
            )
            assert not result.message.tool_calls
            normalized.append((result.message, result.finish_state, result.refused))
        finally:
            await provider.aclose()
    assert normalized[0] == normalized[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code, status, kind",
    [
        ("rate_limit_exceeded", 429, "rate_limit"),
        ("invalid_prompt", 400, "invalid_request"),
        ("server_error", 500, "server"),
        ("vector_store_timeout", 408, "timeout"),
        ("model_not_found", 404, "model_unavailable"),
        ("unsupported_parameter", 400, "unsupported_feature"),
    ],
)
async def test_failed_response_codes_match_http_failure_categories(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    status: int,
    kind: str,
) -> None:
    from agentinstruct import ChatCompletionsProvider, ProviderError

    secret = "private-test-credential"
    monkeypatch.setenv("FAILED_RESPONSE_KEY", secret)
    failed = response(output=[]).json()
    failed["status"] = "failed"
    failed["error"] = {"code": code, "message": "Private error: " + secret}
    for api, adapter, wire in (
        (
            "responses",
            ResponsesProvider,
            httpx.Response(200, json=failed, headers={"x-request-id": "request-1"}),
        ),
        (
            "chat_completions",
            ChatCompletionsProvider,
            httpx.Response(
                status,
                json={"error": failed["error"]},
                headers={"x-request-id": "request-1"},
            ),
        ),
    ):
        transport = FakeTransport(wire)
        provider = adapter(
            ProviderPlan(
                "test", "openai", api, "https://test.example/v1", "FAILED_RESPONSE_KEY"
            ),
            transport=transport,
        )
        try:
            with pytest.raises(ProviderError) as error:
                await provider.generate(
                    ProviderRequest("model", (Message("user", "Act"),))
                )
            assert error.value.kind == kind
            assert error.value.metadata["code"] == code
            assert error.value.metadata["request_id"] == "request-1"
            if api == "responses":
                assert error.value.metadata["response_id"] == "resp-1"
            assert secret not in str(error.value) + canonical_json(error.value.metadata)
            assert "Private error" not in canonical_json(error.value.metadata)
        finally:
            await provider.aclose()
        assert len(transport.requests) == 1 and transport.closed


@pytest.mark.asyncio
async def test_unknown_response_error_code_does_not_persist_untrusted_text() -> None:
    from agentinstruct import ProviderError

    payload = response(output=[]).json()
    payload["status"] = "failed"
    payload["error"] = {"code": "untrusted-code-payload", "message": "sensitive text"}
    provider = ResponsesProvider(
        ProviderPlan(
            "test", "openai-compatible", "responses", "https://test.example/v1", None
        ),
        transport=FakeTransport(httpx.Response(200, json=payload)),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(ProviderRequest("model", (Message("user", "Act"),)))
        assert error.value.kind == "unknown"
        assert error.value.metadata["code"] is None
        assert "untrusted-code-payload" not in canonical_json(error.value.metadata)
        assert "sensitive text" not in canonical_json(error.value.metadata)
    finally:
        await provider.aclose()
