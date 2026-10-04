"""Describe a function to the model and call it with supplied arguments."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    function: Callable[[Mapping[str, Any]], Awaitable[Any]]
    id: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})

    def __post_init__(self) -> None:
        self.id = self.id or getattr(self.function, "__name__", "")

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    async def call(self, arguments: Mapping[str, Any]) -> Any:
        return await self.function(arguments)
