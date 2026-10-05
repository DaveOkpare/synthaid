"""Offline review, Tool privacy, shared segments and final grading."""

import json
from collections.abc import Mapping, Sequence
from typing import Any


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if arguments["label"] != "safe":
        raise ValueError("Rejected Tool call executed")
    return {"label": "safe", "invocation": 1, "seed": arguments["seed"]}


def review(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    message = messages[-1]
    content = message.get("content", "")
    if not isinstance(content, str):
        content = "".join(part.get("text", "") for part in content)
    safe = not content.startswith("DRAFT") and all(
        json.loads(call["arguments"]).get("label") != "reject"
        for call in messages
        if call.get("type") == "function_call"
    )
    return {
        "criteria": {"safe": safe},
        "feedback": "Use accepted wording and a safe label.",
    }


def verify(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"criteria": {"complete": bool(messages and messages[-1].get("content"))}}
