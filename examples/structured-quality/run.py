"""Offline Chat Completions quality gates; no credentials or network calls."""

import asyncio
import json
from pathlib import Path

import httpx

from agentinstruct import ChatCompletionsProvider, ProviderPlan, Runner, TaskPackage


def reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    subject = json.loads(body["messages"][1]["content"])
    decision = {
        "criteria": [
            {"id": item["id"], "passed": True} for item in subject["rubric"]["criteria"]
        ],
        "feedback": "Scripted transport response for this offline example.",
    }
    return httpx.Response(
        200,
        json={
            "id": "offline-judgment",
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(decision),
                    },
                    "finish_reason": "stop",
                }
            ],
        },
    )


def provider(plan: ProviderPlan) -> ChatCompletionsProvider:
    return ChatCompletionsProvider(plan, transport=httpx.MockTransport(reply))


async def main() -> None:
    result = await Runner(provider_factory=provider).run(
        TaskPackage.load(Path(__file__).parent)
    )
    print(result.traces[0].status, result.traces[0].path)


if __name__ == "__main__":
    asyncio.run(main())
