"""Pass prepared task records to an Environment in order."""

from collections.abc import Iterable, Mapping

from agentinstruct.data import FrozenJsonValue, JsonValue
from agentinstruct.execution import Environment
from agentinstruct.store import Episode


class Runner:
    def __init__(
        self,
        environment: Environment,
        tasks: Iterable[Mapping[str, JsonValue | FrozenJsonValue]],
    ) -> None:
        self.environment = environment
        self.tasks = tasks

    async def run(self) -> list[Episode]:
        episodes = []
        for task in self.tasks:
            episodes.append(await self.environment.run(task))
        return episodes
