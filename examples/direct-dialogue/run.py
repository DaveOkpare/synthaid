"""Generate reviewed retail conversations directly from Task definitions."""

import argparse
import asyncio
import json
from collections.abc import Sequence
from typing import Any

from agentinstruct import Agent, Judge, Runner, Task
from agentinstruct.episode import Message


class RetailAgent(Agent):
    async def generate(
        self,
        history: Sequence[Message],
        *,
        client: Any = None,
        role: str = "assistant",
        instruction: str | None = None,
    ) -> Message:
        purchase = json.loads(history[1].content)
        item, days = purchase["item"], purchase["days_since_purchase"]
        if role == "user":
            return Message("user", f"Can I return my {item} after {days} days?")
        decision = (
            "eligible with a receipt" if days <= 30 else "outside the return window"
        )
        return Message(
            "assistant",
            f"Your {item} is {decision}. Our fictional policy allows 30 days.",
            control="complete",
        )


async def main(output: str) -> None:
    judge = Judge(
        check=lambda messages: bool(messages and messages[-1].content.strip())
    )
    assistant = RetailAgent(
        instruction="Apply the fictional 30-day return policy.", reviewer=judge
    )
    user = RetailAgent(instruction="Ask about the supplied purchase.")
    tasks = [
        Task(
            agents={"assistant": assistant, "user": user},
            verifier=judge,
            input={"item": item, "days_since_purchase": days},
        )
        for item, days in (("headphones", 12), ("desk lamp", 45))
    ]
    for episode in await Runner(tasks, output_dir=output).run():
        print(episode.status, episode.path)
        print(json.dumps([message.content for message in episode.messages], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runs/retail")
    asyncio.run(main(parser.parse_args().output))
