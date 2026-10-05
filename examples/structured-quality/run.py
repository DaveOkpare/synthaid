"""Model-backed Judges through the official SDK with an offline transport."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from agentinstruct import Runner
from agentinstruct.adapters.task_files import load_tasks


def reply(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    decision = "Hello Ada."
    if "text" in body:
        criteria = [True for _ in json.loads(body["input"])["criteria"]]
        decision = json.dumps({"criteria": criteria, "feedback": "Offline validation."})
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
                        {"type": "output_text", "text": decision, "annotations": []}
                    ],
                }
            ],
        },
    )


async def main(output: Path) -> None:
    async with AsyncOpenAI(
        base_url="https://example.invalid/v1",
        api_key="offline",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(reply)),
    ) as client:
        tasks = load_tasks(Path(__file__).parent, clients={"judge": client})
        for episode in await Runner(tasks, output_dir=output, client=client).run():
            print(episode.verification, episode.path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs"))
    asyncio.run(main(parser.parse_args().output))
