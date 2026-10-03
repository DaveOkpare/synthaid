"""Open each Task's existing Episode and execute a fresh Environment."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agentinstruct.environment import Environment
from agentinstruct.episode import Episode
from agentinstruct.task import Task


class Runner:
    def __init__(
        self,
        tasks: Iterable[Task],
        *,
        output_dir: str | Path = "runs",
        client: Any = None,
        environment: Any = Environment,
    ) -> None:
        self.tasks, self.output_dir = tasks, Path(output_dir)
        self.client, self.environment = client, environment

    async def run(self) -> list[Episode]:
        episodes = []
        for task in self.tasks:
            task.episode.open(self.output_dir / task.episode.id)
            try:
                environment = self.environment(task, client=self.client)
                await environment.run()
            except BaseException as exc:
                _construction_failure(task.episode, exc)
                raise
            episodes.append(task.episode)
        return episodes


def _construction_failure(episode: Episode, error: BaseException) -> None:
    if episode.sealed:
        return
    try:
        episode.record(
            "environment_error", failure=episode.failure(error, "environment")
        )
        episode.seal("failed", "environment")
    except (OSError, RuntimeError):
        pass
