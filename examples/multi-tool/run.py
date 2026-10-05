"""Prepare Tasks from files and run with an application-owned SDK client."""

import argparse
import asyncio
from pathlib import Path

from openai import AsyncOpenAI

from agentinstruct import Runner
from agentinstruct.adapters.task_files import load_tasks


async def main(output: Path) -> None:
    tasks = load_tasks(Path(__file__).parent)
    async with AsyncOpenAI() as client:
        for episode in await Runner(tasks, output_dir=output, client=client).run():
            print(episode.verification, episode.path)
            for message in episode.messages:
                print(message["role"], message["content"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs"))
    asyncio.run(main(parser.parse_args().output))
