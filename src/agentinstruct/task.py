"""Conversation inputs and the Episode that records their execution."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from agentinstruct.agent import Agent
from agentinstruct.episode import Episode
from agentinstruct.judge import Evaluator


@dataclass
class Task:
    agents: Mapping[Literal["user", "assistant"], Agent]
    input: Mapping[str, Any] = field(default_factory=dict)
    verifier: Evaluator | None = None
    max_turns: int = 20
    episode: Episode = field(default_factory=Episode, init=False)

    def __post_init__(self) -> None:
        if "assistant" not in self.agents or set(self.agents) - {"assistant", "user"}:
            raise ValueError("Task requires assistant and permits only optional user")
        if type(self.max_turns) is not int or self.max_turns < 1:
            raise ValueError("max_turns must be a positive integer")
