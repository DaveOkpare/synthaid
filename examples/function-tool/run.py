"""Prepare ordinary Tasks with the optional file loader and run offline."""

import argparse
import asyncio
from pathlib import Path

from agentinstruct import Runner
from agentinstruct.adapters.task_files import load_tasks


async def main(output: Path) -> None:
    tasks = load_tasks(Path(__file__).parent)
    for episode in await Runner(tasks, output_dir=output).run():
        print(episode.status, episode.path)
        for message in episode.messages:
            print(message.segment, message.actor_id, message.content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs"))
    asyncio.run(main(parser.parse_args().output))
