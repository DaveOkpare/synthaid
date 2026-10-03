"""Open each Task's Episode, invoke its Environment and collect the results."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agentinstruct.environment import Environment, UserSimEnv
from agentinstruct.episode import Episode
from agentinstruct.task import Task


class Runner:
    def __init__(
        self,
        tasks: Iterable[Task],
        *,
        output_dir: str | Path = "runs",
        client: Any = None,
        environment: Environment | None = None,
    ) -> None:
        self.tasks, self.output_dir = tasks, Path(output_dir)
        self.client = client
        self.environment = environment if environment is not None else UserSimEnv()

    async def run(self) -> list[Episode]:
        episodes = []
        for task in self.tasks:
            task.episode.open(self.output_dir / task.episode.id)
            await self.environment.run(task, client=self.client)
            episodes.append(task.episode)
        return episodes
