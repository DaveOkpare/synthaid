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
    schema = body["response_format"]["json_schema"]["schema"]
    criteria = {name: True for name in schema["properties"]["criteria"]["properties"]}
    decision = json.dumps({"criteria": criteria, "feedback": "Offline validation."})
    return httpx.Response(
        200,
        json={
            "id": "offline",
            "model": body["model"],
            "created": 1,
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": decision},
                    "finish_reason": "stop",
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
