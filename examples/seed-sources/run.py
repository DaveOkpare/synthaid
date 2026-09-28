"""Run iterable Seeds offline: uv run python examples/seed-sources/run.py."""

import json
from pathlib import Path

from agentinstruct import (
    Message,
    Observation,
    Runner,
    Seed,
    SeedOrigin,
    TaskPackage,
    generate_sync,
)


class GreetingAgent:
    async def generate(self, observation: Observation) -> Message:
        return Message("assistant", observation.instruction)


if __name__ == "__main__":
    package = TaskPackage.load(Path(__file__).parent)
    result = generate_sync(
        package,
        runner=Runner(agent_factory=lambda _: GreetingAgent()),
        seeds=[
            {"id": "python-a", "name": "Ada"},
            Seed(
                "logical-b",
                {"id": "python-b", "name": "Lin"},
                SeedOrigin("memory:curated-people", 2),
                "",  # The compiler computes the canonical content digest.
            ),
        ],
    )
    print(json.dumps(result.to_dict(), indent=2))
