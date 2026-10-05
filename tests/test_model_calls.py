"""Responses API calls through the real SDK and an offline HTTP transport."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import APIStatusError

from agentinstruct import Agent, Judge, Runner, Task, Tool
from agentinstruct.judge import Criterion, Rubric
from tests.model_fixtures import Transport, assessment, client, function, response


@pytest.mark.asyncio
async def test_stateless_requests_and_application_owned_client(tmp_path: Path) -> None:
    transport = Transport(response(), response())
    borrowed = client(transport)
    tasks = [
        Task(agents={"assistant": Agent("model", "Greet")}, input={"name": "Ada"})
        for _ in range(2)
    ]
    async with borrowed:
        await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed() and transport.closes == 0
    assert transport.closes == 1
    for request, task in zip(transport.requests, tasks, strict=True):
        body = json.loads(request.content)
        assert body["stream"] is False
        assert body["input"] == [
            {"role": "system", "content": "Greet"},
            {"role": "user", "content": '{"name": "Ada"}'},
        ]
        assert task.episode.messages[0]["content"] == "Hello"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["refusal", "length"])
async def test_sdk_status_is_returned_without_custom_validation(failure: str) -> None:
    transport = Transport(response(failure=failure))
    async with client(transport) as borrowed:
        result = await Agent("model").generate([], client=borrowed)
    assert result.status == ("incomplete" if failure == "length" else "completed")
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_agent_passes_structured_output_options_to_responses() -> None:
    format_ = {
        "type": "json_schema",
        "name": "answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"answer": {"type": "integer"}},
            "required": ["answer"],
            "additionalProperties": False,
        },
    }
    transport = Transport(response('{"answer":42}'))
    async with client(transport) as borrowed:
        result = await Agent("model", client=borrowed).generate(
            [{"role": "user", "content": "What is six times seven?"}],
            text={"format": format_},
        )
    assert transport.requests[0].url.path == "/v1/responses"
    assert json.loads(transport.requests[0].content)["text"] == {"format": format_}
    assert json.loads(result.output_text) == {"answer": 42}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_provider_errors_propagate_without_retries(status: int) -> None:
    transport = Transport(
        httpx.Response(
            status,
            json={"error": {"message": "unsafe canary"}},
            headers={"x-request-id": "error-id"},
        )
    )
    async with client(transport) as borrowed:
        with pytest.raises(APIStatusError) as caught:
            await Agent("model").generate(
                [{"role": "user", "content": "Hi"}], client=borrowed
            )
    assert caught.value.status_code == status
    assert len(transport.requests) == 1 and transport.closes == 1


@pytest.mark.asyncio
async def test_usersim_rejects_model_tool_proposals_without_effects(
    tmp_path: Path,
) -> None:
    effects: list[str] = []

    async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
        effects.append(arguments["value"])
        return {"value": arguments["value"]}

    calls = [
        function("one", "one"),
        function("two", "two"),
    ]
    first = response("", output=calls)
    transport = Transport(first, response("Done"))
    async with client(transport) as borrowed:
        task = Task(agents={"assistant": Agent("model", tools=[Tool(lookup)])})
        with pytest.raises(ValueError, match="does not execute Tool calls"):
            await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert not effects and not task.episode.messages
    assert len(transport.requests) == 1
    advertised = json.loads(transport.requests[0].content)["tools"]
    schema = {"name": "lookup", "description": "", "parameters": {"type": "object"}}
    assert advertised == [{"type": "function", **schema}]


@pytest.mark.asyncio
async def test_real_judge_client_call_does_not_serialize_client_credentials(
    tmp_path: Path,
) -> None:
    secret = "credential-canary"
    transport = Transport(
        response("Hello"),
        assessment(True, feedback="Good"),
    )
    async with client(transport, api_key=secret) as borrowed:
        judge = Judge(Rubric([Criterion("Evaluate the reply")], 0.5), "judge", borrowed)
        task = Task(agents={"assistant": Agent("model")}, verifier=judge)
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed()
    assert task.episode.verification is not None and task.episode.verification.passed
    request = transport.requests[1]
    assert request.url.path == "/v1/responses"
    format_ = json.loads(request.content)["text"]["format"]
    assert format_["type"] == "json_schema" and format_["strict"] is True
    assert format_["schema"]["required"] == ["criteria", "feedback"]
    assert secret not in "".join(path.read_text() for path in tmp_path.rglob("*.json*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"x":}', '{"x":NaN}', "[]"])
async def test_tool_arguments_are_returned_as_native_strings(
    arguments: str,
) -> None:
    call = function("call", "unused")
    call["arguments"] = arguments
    transport = Transport(response("", output=[call]))
    async with client(transport) as borrowed:
        result = await Agent("model").generate(
            [{"role": "user", "content": "Call"}], client=borrowed
        )
        assert result.output[0].arguments == arguments
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_same_builtin_agent_uses_independent_clients_and_task_inputs(
    tmp_path: Path,
) -> None:
    import asyncio

    shared = Agent("model", "Base")
    tasks = [
        Task(
            agents={"assistant": shared},
            input={"index": i},
        )
        for i in range(2)
    ]
    first, second = (
        Transport(response("first")),
        Transport(response("second")),
    )
    async with client(first) as one, client(second) as two:
        await asyncio.gather(
            Runner([tasks[0]], output_dir=tmp_path, client=one).run(),
            Runner([tasks[1]], output_dir=tmp_path, client=two).run(),
        )
        assert not one.is_closed() and (not two.is_closed())
    assert [t.episode.messages[0]["content"] for t in tasks] == ["first", "second"]
    for i, transport in enumerate((first, second)):
        assert json.loads(transport.requests[0].content)["input"] == [
            {"role": "system", "content": "Base"},
            {"role": "user", "content": f'{{"index": {i}}}'},
        ]
    assert shared.client is None and shared.instruction == "Base"


@pytest.mark.asyncio
async def test_explicit_agent_client_precedes_runner_default(tmp_path: Path) -> None:
    explicit = Transport(response("explicit"))
    default = Transport()
    async with client(explicit) as chosen, client(default) as borrowed:
        task = Task(agents={"assistant": Agent("model", client=chosen)})
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
        assert not chosen.is_closed() and (not borrowed.is_closed())
    assert task.episode.messages[0]["content"] == "explicit" and (not default.requests)
