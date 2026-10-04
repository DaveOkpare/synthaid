"""Stateless scripted negative controls for review and Tool effects."""

from collections.abc import Sequence
from typing import Any

from agentinstruct.episode import FunctionCall, Message, ToolCall


class ProbeAssistant:
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        feedback = len(history) > 1 and bool(history[-2].tool_calls)
        if any(message.role == "tool" for message in history):
            return Message("assistant", "Accepted scenario", control="complete")
        blocked = history[0].content.strip() == "exhaust" or not feedback
        return Message(
            "assistant",
            "BLOCK_THIS_CALL" if blocked else "",
            tool_calls=(
                ToolCall(
                    "blocked" if blocked else "allowed", FunctionCall("read_scenario")
                ),
            ),
        )


class ProbeUser:
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        if any(message.role == "tool" or message.tool_calls for message in history):
            raise ValueError("Private Tools reached peer")
        return Message("user", "Please summarize the supplied scenario")
