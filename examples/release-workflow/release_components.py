"""Offline review, Tool privacy, shared segments and final grading."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from agentinstruct import Agent
from agentinstruct.episode import FunctionCall, Message, ToolCall


class Participant(Agent):
    async def generate(
        self, history: Sequence[Message], *, role: str = "assistant", **kwargs: Any
    ) -> Message:
        variables = json.loads(history[1].content)
        feedback = history[-1].content.startswith("Private review feedback:")
        if role == "user":
            if any(message.tool_calls or message.role == "tool" for message in history):
                raise ValueError("Private Tool activity reached the user")
            return Message(
                "user", ("User " if feedback else "DRAFT ") + variables["name"]
            )
        results = [message for message in history if message.role == "tool"]
        if not results:
            label = "safe" if feedback else "reject"
            return Message(
                "assistant",
                tool_calls=(
                    ToolCall(
                        label,
                        FunctionCall(
                            "lookup", {"label": label, "seed": variables["case_id"]}
                        ),
                    ),
                ),
            )
        if variables["outcome"] == "failed":
            raise ValueError("Deliberate post-commit failure")
        return Message("assistant", "Final " + variables["name"], control="complete")


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if arguments["label"] != "safe":
        raise ValueError("Rejected Tool call executed")
    return {"label": "safe", "invocation": 1, "seed": arguments["seed"]}


def review(messages: Sequence[Message]) -> dict[str, Any]:
    message = messages[-1]
    safe = not message.content.startswith("DRAFT") and all(
        call.function.arguments.get("label") != "reject" for call in message.tool_calls
    )
    return {
        "criteria": {"safe": safe},
        "feedback": "Use accepted wording and a safe label.",
    }


def verify(messages: Sequence[Message]) -> dict[str, Any]:
    return {
        "criteria": {"complete": bool(messages and messages[-1].control == "complete")}
    }
