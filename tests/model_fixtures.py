"""Official SDK calls through an offline HTTP transport."""

import json
from typing import Any

import httpx
from openai import AsyncOpenAI


class Transport(httpx.AsyncBaseTransport):
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []
        self.closes = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert self.responses, "Unexpected inference request"
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

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
    api: str,
    content: str = "Hello",
    *,
    calls: list[dict[str, Any]] | None = None,
    output: list[dict[str, Any]] | None = None,
    failure: str | None = None,
) -> httpx.Response:
    if api == "chat_completions":
        message = {"role": "assistant", "content": content, "tool_calls": calls}
        if failure == "refusal":
            message["refusal"] = "Cannot comply"
        raw = {
            "id": "completion",
            "model": "model",
            "created": 1,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "length"
                    if failure == "length"
                    else "tool_calls"
                    if calls
                    else "stop",
                }
            ],
        }
    else:
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


def function(api: str, identifier: str, value: str) -> dict[str, Any]:
    declaration = {"name": "lookup", "arguments": json.dumps({"value": value})}
    if api == "responses":
        return {
            "type": "function_call",
            "id": "function-" + identifier,
            "call_id": identifier,
            "status": "completed",
            **declaration,
        }
    return {"type": "function", "id": identifier, "function": declaration}
