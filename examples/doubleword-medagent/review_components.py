"""Stateless scripted negative controls for review and Tool effects."""

from collections.abc import Sequence
from typing import Any

from agentinstruct import Agent
from agentinstruct.episode import FunctionCall, Message, ToolCall


class ProbeAssistant(Agent):
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        feedback = history[-1].content.startswith("Private review feedback:")
        if any(message.role == "tool" for message in history):
            return Message("assistant", "Accepted scenario", control="complete")
        blocked = self.instruction.strip() == "exhaust" or not feedback
        return Message(
            "assistant",
            "BLOCK_THIS_CALL" if blocked else "",
            tool_calls=(
                ToolCall(
                    "blocked" if blocked else "allowed", FunctionCall("read_scenario")
                ),
            ),
        )


class ProbeUser(Agent):
    async def generate(self, history: Sequence[Message], **kwargs: Any) -> Message:
        if any(message.role == "tool" or message.tool_calls for message in history):
            raise ValueError("Private Tools reached peer")
        return Message("user", "Please summarize the supplied scenario")
