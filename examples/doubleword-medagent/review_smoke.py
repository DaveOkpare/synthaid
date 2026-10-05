"""Offline rejection and revision through the SDK, without executing Tools."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from smoke_components import read_scenario

from agentinstruct import Agent, Judge, Runner, Task
from agentinstruct.judge import Criterion, Rubric


def reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if "text" in body:
        messages = json.loads(body["input"])["messages"]
        decision = {
            "criteria": ["BLOCK_THIS_CALL" not in json.dumps(messages[-1])],
            "feedback": "Reply with the accepted scenario.",
        }
        output = [
            {
                "type": "message",
                "id": "judgment",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(decision),
                        "annotations": [],
                    }
                ],
            }
        ]
    else:
        history = body["input"]
        revised = history[-1]["content"] == "Reply with the accepted scenario."
        output = (
            [
                {
                    "type": "message",
                    "id": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Accepted scenario",
                            "annotations": [],
                        }
                    ],
                }
            ]
            if revised
            else [
                {
                    "type": "function_call",
                    "id": "call",
                    "call_id": "BLOCK_THIS_CALL",
                    "status": "completed",
                    "name": "read_scenario",
                    "arguments": "{}",
                }
            ]
        )
    return httpx.Response(
        200,
        json={
            "id": "offline",
            "model": "offline",
            "created_at": 1.0,
            "object": "response",
            "status": "completed",
            "parallel_tool_calls": True,
            "tools": [],
            "tool_choice": "auto",
            "output": output,
        },
    )


async def main(output: Path) -> None:
    reader = read_scenario(
        {
            "id": "read_scenario",
            "description": "Read fixture",
            "input_schema": {"type": "object"},
            "variables": {
                "topic": "fictional",
                "discussion_type": "general",
                "language": "English",
            },
        }
    )
    async with AsyncOpenAI(
        base_url="https://example.invalid/v1",
        api_key="offline",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    ) as client:
        judge = Judge(
            Rubric(
                [
                    Criterion(
                        "Reject BLOCK_THIS_CALL and request the accepted scenario."
                    )
                ],
                0.9,
            ),
            "offline-judge",
            client,
        )
        task = Task(
            agents={"assistant": Agent("offline", tools=[reader], reviewer=judge)},
            verifier=judge,
        )
        for episode in await Runner([task], output_dir=output, client=client).run():
            print(episode.verification, episode.path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/review"))
    asyncio.run(main(parser.parse_args().output))
