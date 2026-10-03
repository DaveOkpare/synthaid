"""Ordered segments continue accepted and private history without Agent state."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentinstruct import Agent
from agentinstruct.episode import FunctionCall, Message, ToolCall


class DemoAgent(Agent):
    async def generate(
        self, history: Sequence[Message], *, role: str = "assistant", **kwargs: Any
    ) -> Message:
        if role == "user":
            return Message("user", "Please look up my greeting for this segment.")
        results = [message for message in history if message.role == "tool"]
        if results:
            return Message(
                "assistant",
                json.loads(results[-1].content)["greeting"],
                control="complete",
            )
        variables = json.loads(history[1].content)
        return Message(
            "assistant",
            "Look up the greeting.",
            tool_calls=(
                ToolCall(
                    "greeting", FunctionCall("lookup", {"name": variables["name"]})
                ),
            ),
        )


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"greeting": f"Hello, {arguments['name']}."}
