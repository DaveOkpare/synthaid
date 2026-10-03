"""Execute and finalize a Task; the default implementation simulates dialogue."""

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from typing import Any, Protocol

from agentinstruct.agent import ReviewExhausted
from agentinstruct.episode import Episode
from agentinstruct.judge import Judge
from agentinstruct.task import Task


class Environment(Protocol):
    async def run(self, task: Task, *, client: Any = None) -> None: ...


class TurnLimitReached(RuntimeError):
    """The configured conversation ended before its completion signal."""


class UserSimEnv:
    async def run(self, task: Task, *, client: Any = None) -> None:
        error: BaseException | None = None
        try:
            _begin(task, client)
            async with asyncio.timeout(task.timeout_seconds):
                await self._generate(task, client)
        except (Exception, asyncio.CancelledError) as exc:
            error = exc
        _finish(task.episode, error)
        await _verify(task)

    async def _generate(self, task: Task, client: Any) -> None:
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


def _begin(task: Task, client: Any) -> None:
    episode = task.episode
    episode.add_secrets(
        client, task.verifier.client if isinstance(task.verifier, Judge) else None
    )
    for agent in task.agents.values():
        episode.add_secrets(
            agent.client,
            agent.reviewer.client if isinstance(agent.reviewer, Judge) else None,
        )
    episode.begin(task.declaration())


def _finish(episode: Episode, error: BaseException | None) -> None:
    if error is not None:
        with suppress(OSError, RuntimeError):
            episode.record("error", failure=episode.failure(error, "environment"))
    state, reason = _outcome(error)
    try:
        episode.seal(state, reason)
    except OSError as exc:
        if error is not None:
            raise error from exc
        raise
    if isinstance(error, (asyncio.CancelledError, OSError)) and not isinstance(
        error, TimeoutError
    ):
        raise error


def _outcome(error: BaseException | None) -> tuple[str, str]:
    if error is None:
        return "terminated", "completed"
    if isinstance(error, asyncio.CancelledError):
        return "failed", "cancelled"
    if isinstance(error, TimeoutError):
        return "truncated", "timeout"
    if isinstance(error, ReviewExhausted):
        return "truncated", "review_exhausted"
    if isinstance(error, TurnLimitReached):
        return "truncated", str(error)
    return "failed", "execution"


async def _verify(task: Task) -> None:
    if task.verifier is None or task.episode.status in {"failed", "invalid"}:
        return
    attempts = len(task.episode.verification)
    try:
        await task.episode.verify(task.verifier)
    except Exception:
        if len(task.episode.verification) == attempts:
            raise
