"""Execute and finalize a Task; the default implementation simulates dialogue."""

import asyncio
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import replace
from typing import Any, Literal, Protocol, cast

from agentinstruct.agent import Agent, ReviewExhausted
from agentinstruct.episode import Episode, Message, canonical_json
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
                reply = await self._turn(task, role, instruction, client)
                turns += 1
                if reply.control == "complete" or "user" not in task.agents:
                    return True, turns
        return False, turns

    async def _turn(
        self, task: Task, role: str, instruction: str, client: Any
    ) -> Message:
        episode, agent = task.episode, task.agents[role]
        context = [Message("system", instruction)]
        if task.input:
            context.append(Message("user", canonical_json(task.input)))
        while True:
            message = await agent.generate(
                (*context, *episode.history(role)),
                client=client,
                role=role,
            )
            accepted = _accept(episode, agent, message, role)
            if not accepted.tool_calls:
                return accepted
            await _execute_tools(episode, agent, accepted)


def _accept(episode: Episode, agent: Agent, message: Message, role: str) -> Message:
    assigned = {tool.id: tool for tool in agent.tools}
    for call in message.tool_calls:
        if call.function.name not in assigned:
            raise ValueError("Tool is not assigned to this Agent")
        assigned[call.function.name].validate(call.function.arguments)
    return episode.append(
        replace(
            message,
            id="",
            role=cast(Literal["assistant", "user"], role),
            actor_id=role,
            evidence={},
            visibility="private" if message.tool_calls else "shared",
        )
    )


async def _execute_tools(episode: Episode, agent: Agent, message: Message) -> None:
    assigned = {tool.id: tool for tool in agent.tools}
    for call in message.tool_calls:
        result = await assigned[call.function.name].call(call.function.arguments)
        episode.append(
            Message(
                "tool",
                canonical_json(result),
                actor_id=message.actor_id,
                tool_call_id=call.id,
                visibility="private",
            )
        )


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
