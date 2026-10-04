"""A custom Generator and ordinary callable Tool."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentinstruct.episode import FunctionCall, Message, ToolCall


class GreetingAgent:
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        if history[-1].role == "tool":
            return Message("assistant", json.loads(history[-1].content)["text"])
        return Message(
            "assistant",
            "Capitalize the greeting.",
            tool_calls=(
                ToolCall(
                    "greeting-1",
                    FunctionCall("uppercase", {"text": history[0].content.strip()}),
                ),
            ),
        )


async def uppercase(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"text": str(arguments["text"]).upper()}
