"""Reviewed conversations through the OpenAI SDK with an offline HTTP fixture."""

import argparse
import asyncio
import json

import httpx
from openai import AsyncOpenAI

from agentinstruct import Agent, Judge, Runner, Task


def reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    purchase = json.loads(body["input"][1]["content"])
    item, days = purchase["item"], purchase["days_since_purchase"]
    if body["model"] == "retail-user":
        content = f"Can I return my {item} after {days} days?"
    else:
        decision = (
            "eligible with a receipt" if days <= 30 else "outside the return window"
        )
        content = f"Your {item} is {decision}. Our fictional policy allows 30 days."
    return httpx.Response(
        200,
        json={
            "id": "offline",
            "model": body["model"],
            "created_at": 1.0,
            "object": "response",
            "status": "completed",
            "parallel_tool_calls": True,
            "tools": [],
            "tool_choice": "auto",
            "output": [
                {
                    "id": "message",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": content, "annotations": []}
                    ],
                }
            ],
        },
    )


async def main(output: str) -> None:
    judge = Judge(check=lambda messages: bool(messages[-1]["content"]))
    assistant = Agent(
        "retail-assistant", "Apply the fictional 30-day return policy.", reviewer=judge
    )
    user = Agent("retail-user", "Ask about the supplied purchase.")
    tasks = [
        Task(
            agents={"user": user, "assistant": assistant},
            verifier=judge,
            input={"item": item, "days_since_purchase": days},
            max_turns=2,
        )
        for item, days in (("headphones", 12), ("desk lamp", 45))
    ]
    async with AsyncOpenAI(
        base_url="https://example.invalid/v1",
        api_key="offline",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    ) as client:
        for episode in await Runner(tasks, output_dir=output, client=client).run():
            print(episode.verification, episode.path)
            print(json.dumps(episode.messages, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runs/retail")
    asyncio.run(main(parser.parse_args().output))
