"""Environments run Tasks; UserSimEnv records a conversation and verifies it."""

import json
from dataclasses import replace
from typing import Any, Protocol

from agentinstruct.episode import Message
from agentinstruct.judge import Judgment
from agentinstruct.task import Task


class Environment(Protocol):
    async def run(self, task: Task, *, client: Any = None) -> None: ...


class UserSimEnv(Environment):
    async def run(self, task: Task, *, client: Any = None) -> None:
        if task.segments or task.timeout_seconds is not None:
            raise ValueError("UserSimEnv does not support segments or deadlines")
        episode, roles = task.episode, task.roles
        episode.metadata = task.declaration()
        context = (
            [Message("user", json.dumps(task.input, allow_nan=False))]
            if task.input
            else []
        )
        for turn in range(min(task.max_turns, task.max_rounds * len(roles))):
            role = roles[turn % len(roles)]
            reply = await task.agents[role].generate(
                (*context, *episode.messages), client=client, role=role
            )
            if reply.tool_calls or (reply.control and role != "assistant"):
                raise ValueError(
                    "UserSimEnv rejects Tool calls and only assistant may complete"
                )
            episode.messages.append(replace(reply, role=role))
            if reply.control == "complete" or len(roles) == 1:
                break
        if task.verifier is not None:
            result = await task.verifier.evaluate(tuple(episode.messages))
            if not isinstance(result, Judgment):
                raise ValueError("Verifier must return a Judgment")
            episode.verification = result
