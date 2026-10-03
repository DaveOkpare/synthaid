"""Offline negative controls demonstrate revisions and rejected Tool isolation."""

import argparse
import asyncio
from pathlib import Path

from review_components import ProbeAssistant, ProbeUser
from smoke_components import read_scenario

from agentinstruct import Judge, Runner, Task
from agentinstruct.episode import Message


def check(messages: tuple[Message, ...]) -> dict[str, object]:
    return {
        "passed": "BLOCK_THIS_CALL" not in messages[-1].content,
        "feedback": "Remove the blocked marker and call read_scenario once.",
    }


async def main(output: Path) -> None:
    reader = read_scenario(
        {
            "id": "read_scenario",
            "description": "Read fixture",
            "input_schema": {"type": "object"},
            "output_schema": None,
            "variables": {
                "topic": "fictional",
                "discussion_type": "general",
                "language": "English",
            },
        }
    )
    judge = Judge(check=check)
    assistant = ProbeAssistant(tools=[reader], reviewer=judge, max_revisions=2)
    task = Task(agents={"assistant": assistant, "user": ProbeUser()}, verifier=judge)
    for episode in await Runner([task], output_dir=output).run():
        print(episode.status, episode.path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/review"))
    asyncio.run(main(parser.parse_args().output))
