"""Official SDK calls through an offline HTTP transport."""

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx
from openai import AsyncOpenAI

from agentinstruct.judge import Judge, Judgment
from agentinstruct.task import Task


class Transport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        *responses: httpx.Response
        | Exception
        | Callable[[httpx.Request], Awaitable[httpx.Response]],
    ) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.closes = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, "Unexpected inference request"
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return await result(request) if callable(result) else result

    async def aclose(self) -> None:
        self.closes += 1


def client(transport: Transport, api_key: str = "offline") -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url="https://offline.example/v1",
        api_key=api_key,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=transport),
    )


def response(
    content: str = "Hello",
    *,
    output: list[dict[str, Any]] | None = None,
    failure: str | None = None,
) -> httpx.Response:
    raw = {
        "id": "response",
        "model": "model",
        "created_at": 1.0,
        "object": "response",
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": "incomplete" if failure == "length" else "completed",
        "output": output
        if output is not None
        else [
            {
                "type": "message",
                "id": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "Cannot comply"}]
                if failure == "refusal"
                else [{"type": "output_text", "text": content, "annotations": []}],
            }
        ],
    }
    if failure == "length":
        raw["incomplete_details"] = {"reason": "max_output_tokens"}
    return httpx.Response(200, json=raw, headers={"x-request-id": "request-1"})


def function(identifier: str, value: str) -> dict[str, Any]:
    return {
        "type": "function_call",
        "id": "function-" + identifier,
        "call_id": identifier,
        "status": "completed",
        "name": "lookup",
        "arguments": json.dumps({"value": value}),
    }


@dataclass
class Check:
    """A domain evaluator stub for tests that do not exercise Judge."""

    check: Callable[[Sequence[Mapping[str, Any]]], Judgment | bool]

    async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
        result = self.check(messages)
        return result if isinstance(result, Judgment) else Judgment(result)


def assessment(*criteria: bool, feedback: str = "") -> httpx.Response:
    return response(json.dumps({"criteria": criteria, "feedback": feedback}))


def task_responses(tasks: Sequence[Task]) -> list[httpx.Response]:
    replies = []
    for task in tasks:
        agents = list(task.agents.values())
        for turn in range(task.max_turns if len(agents) > 1 else 1):
            agent = agents[turn % len(agents)]
            replies.append(response())
            if isinstance(agent.reviewer, Judge) and agent.reviewer.check is None:
                replies.append(
                    assessment(*(True for _ in agent.reviewer.rubric.criteria))
                )
        if isinstance(task.verifier, Judge) and task.verifier.check is None:
            replies.append(assessment(*(True for _ in task.verifier.rubric.criteria)))
    return replies
