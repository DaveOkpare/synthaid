"""Record and finalize Tasks around a domain-specific Environment."""

import asyncio
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from agentinstruct.agent import ReviewExhausted
from agentinstruct.environment import Environment, TurnLimitReached, UserSimEnv
from agentinstruct.episode import Episode
from agentinstruct.judge import Judge
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
            error = await _execute(self.environment, task, self.client)
            _finish(task.episode, error)
            await _verify(task)
            episodes.append(task.episode)
        return episodes


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


async def _execute(
    environment: Environment, task: Task, client: Any
) -> BaseException | None:
    try:
        _begin(task, client)
        async with asyncio.timeout(task.timeout_seconds):
            await environment.run(task, client=client)
    except (Exception, asyncio.CancelledError) as exc:
        return exc
    return None


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
