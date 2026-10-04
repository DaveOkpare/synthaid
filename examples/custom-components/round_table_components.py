"""Supply custom sampling, with callable checks and Tools."""

from collections.abc import Mapping, Sequence
from typing import Any

from agentinstruct.episode import FunctionCall, Message, ToolCall


class Participant:
    async def generate(
        self, history: Sequence[Message], *, role: str = "assistant", **kwargs: Any
    ) -> Message:
        if role == "user":
            return Message("user", "Please return a safe label.")
        if history[-1].role == "tool":
            return Message("assistant", history[-1].content, control="complete")
        label = "safe" if history[-1].content == "Use a safe label." else "reject"
        return Message(
            "assistant",
            "Look up label",
            tool_calls=(ToolCall(label, FunctionCall("lookup", {"label": label})),),
        )


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"label": arguments["label"]}


def review(messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "criteria": {
            "safe": all(
                call.function.arguments["label"] == "safe"
                for call in messages[-1].tool_calls
            )
        },
        "feedback": "Use a safe label.",
    }


def verify(messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "criteria": {"complete": bool(messages and messages[-1].control == "complete")}
    }
