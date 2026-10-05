"""Conversation data recorded by Runner."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypedDict
from uuid import uuid4

if TYPE_CHECKING:
    from agentinstruct.judge import Judgment


class Message(TypedDict):
    role: Literal["system", "developer", "user", "assistant"]
    content: str


@dataclass
class Episode:
    id: str = field(default_factory=lambda: uuid4().hex)
    messages: list[Message] = field(default_factory=list)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    verification: "Judgment | None" = None
    path: Path | None = None
