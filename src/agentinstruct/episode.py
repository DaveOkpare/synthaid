"""Conversation values and a data-only trace record."""

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from agentinstruct.judge import Judgment


@dataclass(frozen=True)
class FunctionCall:
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool function requires a name")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("Tool arguments must be an object")
        json.dumps(dict(self.arguments), allow_nan=False)
        object.__setattr__(self, "arguments", deepcopy(dict(self.arguments)))


@dataclass(frozen=True)
class ToolCall:
    id: str
    function: FunctionCall
    type: Literal["function"] = "function"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id.strip()
            or self.type != "function"
        ):
            raise ValueError("Tool calls require a stable ID and function type")
        if not isinstance(self.function, FunctionCall):
            raise ValueError("Tool calls require a FunctionCall")


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    actor_id: str | None = None
    control: Literal["complete"] | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Unknown message role")
        if not isinstance(self.content, str) or self.control not in {None, "complete"}:
            raise ValueError("Messages require text and a supported completion signal")
        if any(not isinstance(call, ToolCall) for call in self.tool_calls):
            raise ValueError("Invalid Tool call")
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))


@dataclass
class Episode:
    id: str = field(default_factory=lambda: uuid4().hex)
    messages: list[Message] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    verification: "Judgment | None" = None
    path: Path | None = None
