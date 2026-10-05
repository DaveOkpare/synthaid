"""Environments run Tasks; UserSimEnv records a conversation and verifies it."""

import json
from itertools import cycle, islice
from typing import Any, Protocol

from agentinstruct.episode import Message
from agentinstruct.judge import Judgment
from agentinstruct.task import Task


class Environment(Protocol):
    async def run(self, task: Task, *, client: Any = None) -> None: ...


class UserSimEnv(Environment):
    async def run(self, task: Task, *, client: Any = None) -> None:
        episode = task.episode
        episode.metadata = {**episode.metadata, "input": task.input}
        context = (
            [Message(role="user", content=json.dumps(task.input, allow_nan=False))]
            if task.input
            else []
        )
        for role, agent in islice(cycle(task.agents.items()), task.max_turns):
            incoming = list(context) if not agent.history else []
            if episode.messages:
                incoming.append(
                    Message(role="user", content=episode.messages[-1]["content"])
                )
            result = await agent.generate(incoming, client=client)
            if any(item.type == "function_call" for item in result.output):
                raise ValueError("UserSimEnv does not execute Tool calls")
            episode.messages.append(Message(role=role, content=result.output_text))
            if len(task.agents) == 1:
                break
        if task.verifier is not None:
            result = await task.verifier.evaluate(tuple(episode.messages))
            if not isinstance(result, Judgment):
                raise ValueError("Verifier must return a Judgment")
            episode.verification = result
