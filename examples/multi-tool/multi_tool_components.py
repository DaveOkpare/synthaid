"""Ordered Tool calls with a declared execution error result."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentinstruct import Agent
from agentinstruct.episode import FunctionCall, Message, ToolCall


class LabelAgent(Agent):
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        results = [
            json.loads(message.content) for message in history if message.role == "tool"
        ]
        if results:
            return Message(
                "assistant",
                " | ".join(result.get("summary", "Unavailable") for result in results),
            )
        labels = (history[0].content.strip(), "missing", "Grace")
        return Message(
            "assistant",
            "Summarize labels.",
            tool_calls=tuple(
                ToolCall(f"label-{index}", FunctionCall("summarize", {"text": label}))
                for index, label in enumerate(labels)
            ),
        )


async def summarize(arguments: Mapping[str, Any]) -> dict[str, Any]:
    text = str(arguments["text"])
    if text == "missing":
        raise ValueError("The offline fixture deliberately simulates a failure")
    return {"summary": text.upper()}
