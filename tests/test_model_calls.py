"""Parity at the Agent/Judge interface using real SDK and offline HTTP calls."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agentinstruct import Agent, Judge, Runner, Task, Tool
from agentinstruct.agent import ModelError
from agentinstruct.episode import Message
from tests.model_fixtures import Transport, client, function, response


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
async def test_stateless_requests_and_application_owned_client(
    api: str, tmp_path: Path
) -> None:
    transport = Transport(response(api), response(api))
    borrowed = client(transport)
    tasks = [
        Task(
            agents={"assistant": Agent("model", "Greet", api=api)},
            input={"name": "Ada"},
        )
        for _ in range(2)
    ]
    async with borrowed:
        await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed() and transport.closes == 0
    assert transport.closes == 1
    for request, task in zip(transport.requests, tasks, strict=True):
        body = json.loads(request.content)
        assert body["store"] is False and body["stream"] is False
        assert body["input" if api == "responses" else "messages"] == [
            {"role": "system", "content": "Greet"},
            {"role": "user", "content": '{"name":"Ada"}'},
        ]
        assert task.episode.messages[0].content == "Hello"
        assert task.episode.events[2]["data"] or task.episode.events


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize("failure", ["refusal", "length"])
async def test_refusal_and_incomplete_evidence(
    api: str, failure: str, tmp_path: Path
) -> None:
    transport = Transport(response(api, failure=failure), response(api))
    async with client(transport) as borrowed:
        tasks = [Task(agents={"assistant": Agent("model", api=api)}) for _ in range(2)]
        await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed()
    assert tasks[0].episode.status == "failed" and not tasks[0].episode.messages
    assert tasks[1].episode.messages[0].content == "Hello"
    error = next(
        e for e in tasks[0].episode.events if e["kind"] == "agent_generate_error"
    )
    assert error["data"]["failure"]["kind"] == (
        "refusal" if failure == "refusal" else "incomplete"
    )
    assert error["data"]["model_call"]["response_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize(
    "status, kind",
    [
        (401, "authentication"),
        (403, "authorization"),
        (429, "rate_limit"),
        (500, "server"),
    ],
)
async def test_classified_errors_never_retry_or_persist_error_body(
    api: str, status: int, kind: str
) -> None:
    transport = Transport(
        httpx.Response(
            status,
            json={"error": {"message": "unsafe canary"}},
            headers={"x-request-id": "error-id"},
        )
    )
    async with client(transport) as borrowed:
        with pytest.raises(ModelError) as caught:
            await Agent("model", api=api).generate(
                [Message("user", "Hi")], client=borrowed
            )
    assert caught.value.kind == kind and "unsafe canary" not in str(
        caught.value.evidence
    )
    assert len(transport.requests) == 1 and transport.closes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
async def test_ordered_tool_effects_private_history_and_reasoning_continuation(
    api: str, tmp_path: Path
) -> None:
    effects: list[str] = []

    async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
        effects.append(arguments["value"])
        return {"value": arguments["value"]}

    calls = [function(api, "one", "one"), function(api, "two", "two")]
    reasoning = {
        "type": "reasoning",
        "id": "reasoning",
        "summary": [{"type": "summary_text", "text": "private"}],
        "encrypted_content": "exact-opaque",
    }
    first = response(
        api,
        "",
        output=[reasoning, calls[0], calls[1]] if api == "responses" else None,
        calls=calls if api != "responses" else None,
    )
    transport = Transport(first, response(api, "Done"))
    async with client(transport) as borrowed:
        task = Task(agents={"assistant": Agent("model", tools=[Tool(lookup)], api=api)})
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert effects == ["one", "two"]
    assert [m.role for m in task.episode.messages] == [
        "assistant",
        "tool",
        "tool",
        "assistant",
    ]
    assert [m.content for m in task.episode.history("user")] == ["Done"]
    body = json.loads(transport.requests[1].content)
    if api == "responses":
        assert (
            next(item for item in body["input"] if item.get("type") == "reasoning")
            == reasoning
        )
    else:
        assert [
            json.loads(call["function"]["arguments"])
            for call in body["messages"][1]["tool_calls"]
        ] == [{"value": "one"}, {"value": "two"}]


class Output(BaseModel):
    approved: bool


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize(
    "content, error",
    [
        ('{"approved":true}', None),
        ('{"approved":1}', "schema_mismatch"),
        ('{"approved":true,"approved":false}', "invalid_json"),
    ],
)
async def test_local_structured_validation(
    api: str, content: str, error: str | None
) -> None:
    transport = Transport(response(api, content))
    async with client(transport) as borrowed:
        agent = Agent("model", api=api, output_schema=Output)
        if error:
            with pytest.raises(ModelError) as caught:
                await agent.generate([Message("user", "Judge")], client=borrowed)
            assert caught.value.kind == error
        else:
            proposal = await agent.generate([Message("user", "Judge")], client=borrowed)
            assert isinstance(proposal, Message)
            assert proposal.content == content
    body = json.loads(transport.requests[0].content)
    schema = (
        body["text"]["format"]["schema"]
        if api == "responses"
        else body["response_format"]["json_schema"]["schema"]
    )
    assert schema["additionalProperties"] is False and schema["required"] == [
        "approved"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
async def test_real_judge_client_call_and_redaction(api: str, tmp_path: Path) -> None:
    secret = "credential-canary"
    transport = Transport(
        response(api, secret),
        response(api, '{"passed":true,"feedback":"' + secret + '"}'),
    )
    async with client(transport, api_key=secret) as borrowed:
        judge = Judge(client=borrowed, model="judge", prompt="Evaluate", api=api)
        task = Task(agents={"assistant": Agent("model", api=api)}, verifier=judge)
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed()
    assert task.episode.status == "accepted"
    assert secret not in "".join(path.read_text() for path in tmp_path.rglob("*.json*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize("arguments", ['{"x":1,"x":2}', '{"x":NaN}', "[]"])
async def test_malformed_tool_arguments_are_rejected_by_direct_generation(
    api: str, arguments: str
) -> None:
    call = function(api, "call", "unused")
    (call if api == "responses" else call["function"])["arguments"] = arguments
    transport = Transport(
        response(
            api,
            "",
            output=[call] if api == "responses" else None,
            calls=[call] if api != "responses" else None,
        )
    )
    async with client(transport) as borrowed:
        with pytest.raises(ModelError) as error:
            await Agent("model", api=api).generate(
                [Message("user", "Call")], client=borrowed
            )
    assert error.value.kind == "malformed_response" and len(transport.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
async def test_duplicate_call_ids_are_rejected_before_acceptance(api: str) -> None:
    calls = [function(api, "same", "one"), function(api, "same", "two")]
    if api == "responses":
        calls[1]["id"] = "different-item-id"
    transport = Transport(
        response(
            api,
            "",
            output=calls if api == "responses" else None,
            calls=calls if api != "responses" else None,
        )
    )
    async with client(transport) as borrowed:
        with pytest.raises(ModelError, match="malformed_response"):
            await Agent("model", api=api).generate([], client=borrowed)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["empty_choices", "wrong_role", "missing_created", "inconsistent_finish"]
)
async def test_sdk_validation_and_local_chat_contracts(failure: str) -> None:
    raw = response("chat_completions").json()
    if failure == "empty_choices":
        raw["choices"] = []
    elif failure == "wrong_role":
        raw["choices"][0]["message"]["role"] = "user"
    elif failure == "missing_created":
        del raw["created"]
    else:
        raw["choices"][0]["finish_reason"] = "tool_calls"
    transport = Transport(httpx.Response(200, json=raw))
    async with client(transport) as borrowed:
        with pytest.raises(ModelError, match="malformed_response"):
            await Agent("model").generate([], client=borrowed)


@pytest.mark.asyncio
async def test_same_builtin_agent_uses_independent_clients_and_active_instructions(
    tmp_path: Path,
) -> None:
    import asyncio

    shared = Agent("model", "Base")
    tasks = [
        Task(
            agents={"assistant": shared},
            segments=[{"name": str(i), "instructions": {"assistant": str(i)}}],
        )
        for i in range(2)
    ]
    first, second = (
        Transport(response("chat_completions", "first")),
        Transport(response("chat_completions", "second")),
    )
    async with client(first) as one, client(second) as two:
        await asyncio.gather(
            Runner([tasks[0]], output_dir=tmp_path, client=one).run(),
            Runner([tasks[1]], output_dir=tmp_path, client=two).run(),
        )
        assert not one.is_closed() and not two.is_closed()
    assert [t.episode.messages[0].content for t in tasks] == ["first", "second"]
    assert (
        json.loads(first.requests[0].content)["messages"][0]["content"] == "Base\n\n0"
    )
    assert (
        json.loads(second.requests[0].content)["messages"][0]["content"] == "Base\n\n1"
    )
    assert shared.client is None and shared.instruction == "Base"


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize(
    "content,error",
    [
        (
            ' {"checks":[{"passed":true,"label":"good","note":null}],'
            '"day":"2026-09-28"}',
            None,
        ),
        (
            '{"checks":[{"passed":"true","label":"good","note":null}],"day":"2026-09-28"}',
            "schema_mismatch",
        ),
        ('{"checks":[],"day":"not-a-date"}', "schema_mismatch"),
        ('{"checks":[],"day":1e999}', "invalid_json"),
    ],
)
async def test_nested_typed_contracts_keep_alias_enum_null_and_date(
    api: str, content: str, error: str | None
) -> None:
    from datetime import date
    from enum import StrEnum

    from pydantic import ConfigDict, Field

    class Label(StrEnum):
        good = "good"
        bad = "bad"

    class Finding(BaseModel):
        model_config = ConfigDict(extra="forbid")
        passed: bool
        label: Label
        note: str | None

    class Report(BaseModel):
        model_config = ConfigDict(extra="forbid")
        findings: list[Finding] = Field(alias="checks")
        day: date

    transport = Transport(response(api, content))
    async with client(transport) as borrowed:
        agent = Agent("model", api=api, output_schema=Report)
        if error:
            with pytest.raises(ModelError) as caught:
                await agent.generate([], client=borrowed)
            assert caught.value.kind == error
        else:
            proposal = await agent.generate([], client=borrowed)
            assert isinstance(proposal, Message) and proposal.content == content


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array", "items": {"type": "string"}},
        {"type": "object", "properties": {}, "additionalProperties": True},
        {"$ref": "https://remote.invalid/schema"},
        {
            "type": "object",
            "properties": {"x": {"type": ["object", "null"], "properties": {}}},
            "required": ["x"],
            "additionalProperties": False,
        },
        {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
            "allOf": [],
        },
    ],
)
def test_unsupported_structured_schemas_fail_during_inert_construction(
    schema: Any,
) -> None:
    with pytest.raises((ValueError, KeyError)):
        Agent("model", output_schema=schema)


@pytest.mark.parametrize("api", ["responses", "chat_completions"])
@pytest.mark.parametrize(
    "extra",
    [
        {"previous_response_id": "hidden"},
        {"store": True},
        {"stream": True},
        {"conversation": "shared"},
        {"n": 2},
    ],
)
@pytest.mark.asyncio
async def test_extra_options_cannot_override_stateless_execution(
    api: str, extra: dict[str, Any]
) -> None:
    transport = Transport()
    async with client(transport) as borrowed:
        with pytest.raises(ModelError, match="invalid_request"):
            await Agent("model", api=api, extra_body=extra).generate(
                [], client=borrowed
            )
    assert not transport.requests


@pytest.mark.asyncio
async def test_explicit_agent_client_precedes_runner_default(tmp_path: Path) -> None:
    explicit = Transport(response("chat_completions", "explicit"))
    default = Transport()
    async with client(explicit) as chosen, client(default) as borrowed:
        task = Task(agents={"assistant": Agent("model", client=chosen)})
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
        assert not chosen.is_closed() and not borrowed.is_closed()
    assert task.episode.messages[0].content == "explicit" and not default.requests
