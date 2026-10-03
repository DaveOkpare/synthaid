"""A domain execution seam and the default assistant/user conversation."""

from collections.abc import Mapping
from typing import Any, Protocol

from agentinstruct.task import Task


class Environment(Protocol):
    async def run(self, task: Task, *, client: Any = None) -> None: ...


class TurnLimitReached(RuntimeError):
    """The configured conversation ended before its completion signal."""


class UserSimEnv:
    async def run(self, task: Task, *, client: Any = None) -> None:
        turns = 0
        for segment in task.segments or ({"name": None, "instructions": {}},):
            task.episode.activate(segment["name"], segment["instructions"])
            complete, turns = await self._conversation(
                task, segment["instructions"], turns, client
            )
            if not complete:
                raise TurnLimitReached("turn_limit")

    async def _conversation(
        self, task: Task, additions: Mapping[str, str], turns: int, client: Any
    ) -> tuple[bool, int]:
        for _ in range(task.max_rounds if "user" in task.agents else 1):
            for role in task.roles:
                if turns >= task.max_turns:
                    return False, turns
                agent = task.agents[role]
                instruction = agent.instruction
                if role in additions:
                    instruction += "\n\n" + additions[role]
                reply = await agent.turn(
                    task.episode, instruction=instruction, role=role, client=client
                )
                turns += 1
                if reply.control == "complete" or "user" not in task.agents:
                    return True, turns
        return False, turns
