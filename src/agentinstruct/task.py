"""Inert Task definitions automatically own one identified Episode."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, cast

from agentinstruct.agent import Agent
from agentinstruct.episode import Episode, freeze
from agentinstruct.judge import Evaluator, evaluation_settings


@dataclass(frozen=True)
class Task:
    agents: Mapping[str, Agent]
    input: Mapping[str, Any] = field(default_factory=dict)
    segments: Sequence[Mapping[str, Any]] = ()
    verifier: Evaluator | None = None
    max_rounds: int = 10
    max_turns: int = 100
    initiator: str = "user"
    timeout_seconds: float | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    episode: Episode = field(default_factory=Episode, init=False, compare=False)

    def __post_init__(self) -> None:
        _participants(self.agents)
        object.__setattr__(self, "agents", MappingProxyType(dict(self.agents)))
        if not isinstance(self.input, Mapping) or not isinstance(
            self.provenance, Mapping
        ):
            raise ValueError("Task input and provenance must be ordinary mappings")
        object.__setattr__(self, "input", freeze(self.input))
        segments = tuple(_segment(item, self.agents) for item in self.segments)
        object.__setattr__(self, "segments", segments)
        object.__setattr__(self, "provenance", freeze(self.provenance))
        _limits(self)
        if self.verifier is not None and not isinstance(self.verifier, Evaluator):
            raise ValueError("Task verifier must implement evaluate(messages)")

    def declaration(self) -> dict[str, Any]:
        return {
            **dict(self.provenance),
            "variables": self.input,
            "agents": {
                role: {
                    "model": agent.model,
                    "base_instruction": agent.instruction,
                    "tools": [tool.declaration() for tool in agent.tools],
                    "max_revisions": agent.max_revisions,
                    "reviewer": evaluation_settings(agent.reviewer),
                    "target": role == "assistant",
                }
                for role, agent in self.agents.items()
            },
            "verifier": evaluation_settings(self.verifier),
            "segments": self.segments,
            "timeout_seconds": self.timeout_seconds,
        }

    @property
    def roles(self) -> tuple[str, ...]:
        if "user" not in self.agents:
            return ("assistant",)
        return (
            ("user", "assistant") if self.initiator == "user" else ("assistant", "user")
        )


def _segment(
    value: Mapping[str, Any], agents: Mapping[str, Agent]
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"name", "instructions"}:
        raise ValueError("Segment must declare name and instruction additions")
    if not isinstance(value.get("name"), str) or not value["name"].strip():
        raise ValueError("Segment requires a nonempty name")
    instructions = value.get("instructions", {})
    if not isinstance(instructions, Mapping) or set(instructions) - set(agents):
        raise ValueError("Segment instructions must address configured participants")
    if any(not isinstance(text, str) for text in instructions.values()):
        raise ValueError("Segment instructions must be text")
    return cast(
        Mapping[str, Any], freeze({"name": value["name"], "instructions": instructions})
    )


def _limits(task: Task) -> None:
    if any(
        type(limit) is not int or limit < 1
        for limit in (task.max_rounds, task.max_turns)
    ):
        raise ValueError("Task execution limits must be positive integers")
    if task.initiator not in {"assistant", "user"}:
        raise ValueError("Task initiator must be assistant or user")
    if task.timeout_seconds is not None and (
        isinstance(task.timeout_seconds, bool)
        or not math.isfinite(task.timeout_seconds)
        or task.timeout_seconds <= 0
    ):
        raise ValueError("Task timeout must be finite and positive")
    names = [segment["name"] for segment in task.segments]
    if len(names) != len(set(names)):
        raise ValueError("Segment names must be unique")


def _participants(agents: Mapping[str, Agent]) -> None:
    if (
        not isinstance(agents, Mapping)
        or "assistant" not in agents
        or set(agents) - {"assistant", "user"}
    ):
        raise ValueError("Task requires assistant and permits only optional user")
    if any(not isinstance(agent, Agent) for agent in agents.values()):
        raise ValueError("Task participant entries must be Agent instances")
