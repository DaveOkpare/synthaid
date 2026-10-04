"""Run Tasks, save their traces and collect the resulting Episodes."""

import json
import os
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

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
            destination = self.output_dir / task.episode.id
            destination.mkdir(parents=True)
            task.episode.path = destination / "trace.json"
            try:
                await self.environment.run(task, client=self.client)
            finally:
                self._save(task.episode)
            episodes.append(task.episode)
        return episodes

    def _save(self, episode: Episode) -> None:
        assert episode.path is not None
        data = vars(episode).copy()
        del data["path"]
        payload = json.dumps(data, default=asdict, allow_nan=False)
        temporary = episode.path.with_suffix(f".{uuid4().hex}.tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(episode.path)
