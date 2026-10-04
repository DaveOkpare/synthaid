"""Parity at the Agent/Judge interface using real SDK and offline HTTP calls."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from openai import APIStatusError

from agentinstruct import Agent, Judge, Runner, Task, Tool
from agentinstruct.episode import Message
from tests.model_fixtures import Transport, client, function, response


@pytest.mark.asyncio
async def test_stateless_requests_and_application_owned_client(tmp_path: Path) -> None:
    transport = Transport(response("chat_completions"), response("chat_completions"))
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
        assert body["store"] is False and body["stream"] is False
        assert body["messages"] == [
            {"role": "system", "content": "Greet"},
            {"role": "user", "content": '{"name": "Ada"}'},
        ]
        assert task.episode.messages[0].content == "Hello"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["refusal", "length"])
async def test_refusal_and_incomplete_samples_fail_generation(
    failure: str, tmp_path: Path
) -> None:
    transport = Transport(
        response("chat_completions", failure=failure), response("chat_completions")
    )
    async with client(transport) as borrowed:
        tasks = [Task(agents={"assistant": Agent("model")}) for _ in range(2)]
        with pytest.raises(RuntimeError, match="did not complete"):
            await Runner(tasks, output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed()
    assert not tasks[0].episode.messages
    assert tasks[1].episode.path is None
    assert len(transport.requests) == 1


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
            await Agent("model").generate([Message("user", "Hi")], client=borrowed)
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
        function("chat_completions", "one", "one"),
        function("chat_completions", "two", "two"),
    ]
    first = response("chat_completions", "", output=None, calls=calls)
    transport = Transport(first, response("chat_completions", "Done"))
    async with client(transport) as borrowed:
        task = Task(agents={"assistant": Agent("model", tools=[Tool(lookup)])})
        with pytest.raises(ValueError, match="rejects Tool calls"):
            await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert not effects and not task.episode.messages
    assert len(transport.requests) == 1
    advertised = json.loads(transport.requests[0].content)["tools"]
    assert advertised == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "",
                "parameters": {"type": "object"},
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("api", ["responses", "chat_completions"])
async def test_real_judge_client_call_does_not_serialize_client_credentials(
    api: str, tmp_path: Path
) -> None:
    secret = "credential-canary"
    transport = Transport(
        response("chat_completions", "Hello"),
        response(api, '{"passed":true,"feedback":"Good"}'),
    )
    async with client(transport, api_key=secret) as borrowed:
        judge = Judge(client=borrowed, model="judge", prompt="Evaluate", api=api)
        task = Task(agents={"assistant": Agent("model")}, verifier=judge)
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
        assert not borrowed.is_closed()
    assert task.episode.verification is not None and task.episode.verification.passed
    assert secret not in "".join(path.read_text() for path in tmp_path.rglob("*.json*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", ['{"x":}', '{"x":NaN}', "[]"])
async def test_malformed_tool_arguments_are_rejected_by_direct_generation(
    arguments: str,
) -> None:
    call = function("chat_completions", "call", "unused")
    call["function"]["arguments"] = arguments
    transport = Transport(response("chat_completions", "", output=None, calls=[call]))
    async with client(transport) as borrowed:
        with pytest.raises(ValueError):
            await Agent("model").generate([Message("user", "Call")], client=borrowed)
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
        Transport(response("chat_completions", "first")),
        Transport(response("chat_completions", "second")),
    )
    async with client(first) as one, client(second) as two:
        await asyncio.gather(
            Runner([tasks[0]], output_dir=tmp_path, client=one).run(),
            Runner([tasks[1]], output_dir=tmp_path, client=two).run(),
        )
        assert not one.is_closed() and (not two.is_closed())
    assert [t.episode.messages[0].content for t in tasks] == ["first", "second"]
    for i, transport in enumerate((first, second)):
        assert json.loads(transport.requests[0].content)["messages"] == [
            {"role": "system", "content": "Base"},
            {"role": "user", "content": f'{{"index": {i}}}'},
        ]
    assert shared.client is None and shared.instruction == "Base"


@pytest.mark.asyncio
async def test_explicit_agent_client_precedes_runner_default(tmp_path: Path) -> None:
    explicit = Transport(response("chat_completions", "explicit"))
    default = Transport()
    async with client(explicit) as chosen, client(default) as borrowed:
        task = Task(agents={"assistant": Agent("model", client=chosen)})
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
        assert not chosen.is_closed() and (not borrowed.is_closed())
    assert task.episode.messages[0].content == "explicit" and (not default.requests)
