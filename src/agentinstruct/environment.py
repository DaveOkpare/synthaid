"""Execute one Task's segments into its existing Episode; borrow model clients."""

import asyncio
from collections.abc import Coroutine, Sequence
from contextlib import AsyncExitStack, suppress
from typing import Any

from agentinstruct.agent import Agent, ReviewExhausted
from agentinstruct.episode import Episode
from agentinstruct.judge import Judge, JudgeError
from agentinstruct.task import Task


class Environment:
    def __init__(
        self, task: Task, *, client: Any = None, resources: Sequence[Any] = ()
    ) -> None:
        if not isinstance(task, Task):
            raise ValueError("Environment requires a Task")
        self.task, self.client, self.resources = task, client, tuple(resources)
        self.verifier = _verifier(task, client)
        _dependencies(task, client)

    async def run(self) -> None:
        episode = self.task.episode
        _collect_secrets(episode, self.task, self.client, self.verifier)
        episode.begin(_metadata(self.task, self.verifier))
        primary = await self._execute()
        _finish_generation(episode, primary)
        if isinstance(primary, (asyncio.CancelledError, OSError)) and not isinstance(
            primary, TimeoutError
        ):
            raise primary
        if self.verifier is not None and episode.status not in {"failed", "invalid"}:
            await _final_judgment(episode, self.verifier)

    async def _execute(self) -> BaseException | None:
        stack = AsyncExitStack()
        primary: BaseException | None = None
        try:
            async with asyncio.timeout(self.task.timeout_seconds):
                for resource in self.resources:
                    await stack.enter_async_context(resource)
                await self._generate()
        except (Exception, asyncio.CancelledError) as exc:
            primary = exc
        return await _finish_cleanup(stack, self.task.episode, primary)

    async def _generate(self) -> None:
        turns = 0
        for segment in self.task.segments or ({"name": None, "instructions": {}},):
            self.task.episode.activate(segment["name"], segment["instructions"])
            complete, turns = await self._conversation(segment["instructions"], turns)
            if not complete:
                raise _Truncated("turn_limit")

    async def _conversation(self, additions: Any, turns: int) -> tuple[bool, int]:
        roles = _roles(self.task)
        episode = self.task.episode
        for _ in range(self.task.max_rounds if len(roles) == 2 else 1):
            for role in roles:
                if turns >= self.task.max_turns:
                    return False, turns
                agent = self.task.agents[role]
                instruction = agent.instruction + (
                    "\n\n" + additions[role] if role in additions else ""
                )
                inputs = {"role": role, "client": self.client}
                reply = await agent.turn(episode, instruction=instruction, **inputs)
                turns += 1
                if reply.control == "complete" or len(roles) == 1:
                    return True, turns
        return False, turns


class _Truncated(RuntimeError):
    pass


def _dependencies(task: Task, client: Any) -> None:
    for agent in task.agents.values():
        if type(agent).generate is Agent.generate and (
            not agent.model or (agent.client is None and client is None)
        ):
            raise ValueError("Model Agent requires an explicitly supplied model client")


def _verifier(task: Task, client: Any) -> Judge | None:
    if isinstance(task.verifier, Judge) or task.verifier is None:
        return task.verifier
    settings = dict(task.verifier)
    if "check" not in settings:
        settings.setdefault("client", client)
    return Judge(**settings)


def _collect_secrets(
    episode: Episode, task: Task, client: Any, verifier: Judge | None
) -> None:
    episode.add_secrets(client, verifier.client if verifier else None)
    for agent in task.agents.values():
        episode.add_secrets(
            agent.client, agent.reviewer.client if agent.reviewer else None
        )


def _metadata(task: Task, verifier: Judge | None) -> dict[str, Any]:
    return {
        **dict(task.provenance),
        "variables": task.input,
        "agents": {
            role: {**agent.declaration(), "target": role == "assistant"}
            for role, agent in task.agents.items()
        },
        "verifier": verifier.declaration() if verifier else None,
        "segments": task.segments,
        "timeout_seconds": task.timeout_seconds,
    }


def _finish_generation(episode: Episode, primary: BaseException | None) -> None:
    if primary is not None:
        with suppress(OSError, RuntimeError):
            episode.record("error", failure=episode.failure(primary, "environment"))
    state, reason = _outcome(primary)
    try:
        episode.seal(state, reason)
    except OSError as exc:
        if primary is not None:
            raise primary from exc
        raise


def _outcome(error: BaseException | None) -> tuple[str, str]:
    if error is None:
        return "terminated", "completed"
    if isinstance(error, asyncio.CancelledError):
        return "failed", "cancelled"
    if isinstance(error, TimeoutError):
        return "truncated", "timeout"
    if isinstance(error, ReviewExhausted):
        return "truncated", "review_exhausted"
    if isinstance(error, _Truncated):
        return "truncated", str(error)
    return "failed", "execution"


async def _cleanup(stack: AsyncExitStack) -> None:
    async with asyncio.timeout(5.0):
        await stack.aclose()


async def _complete_cleanup(operation: Coroutine[Any, Any, None]) -> bool:
    task = asyncio.create_task(operation)
    interrupted = False
    while True:
        try:
            await asyncio.shield(task)
            return interrupted
        except asyncio.CancelledError:
            interrupted = True
            if task.done():
                if not task.cancelled():
                    task.result()
                return interrupted


async def _finish_cleanup(
    stack: AsyncExitStack, episode: Episode, primary: BaseException | None
) -> BaseException | None:
    try:
        if await _complete_cleanup(_cleanup(stack)) and primary is None:
            primary = asyncio.CancelledError()
    except (Exception, asyncio.CancelledError) as exc:
        with suppress(OSError, RuntimeError):
            episode.record("cleanup_error", failure=episode.failure(exc, "cleanup"))
        if primary is None:
            primary = (
                exc
                if isinstance(exc, asyncio.CancelledError)
                else RuntimeError("Execution resource cleanup failed")
            )
    return primary


def _roles(task: Task) -> tuple[str, ...]:
    if "user" not in task.agents:
        return ("assistant",)
    return ("user", "assistant") if task.initiator == "user" else ("assistant", "user")


async def _final_judgment(episode: Episode, judge: Judge) -> None:
    try:
        await episode.verify(judge)
    except (JudgeError, TimeoutError):
        return
