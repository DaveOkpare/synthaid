"""Callable checks and Tools for native model Agents."""

import json
from collections.abc import Mapping, Sequence
from typing import Any


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"label": arguments["label"]}


def review(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {
        "criteria": {
            "safe": all(
                json.loads(call["arguments"])["label"] == "safe"
                for call in messages
                if call.get("type") == "function_call"
            )
        },
        "feedback": "Use a safe label.",
    }


def verify(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"criteria": {"complete": bool(messages and messages[-1].get("content"))}}
