"""Offline review, Tool privacy, shared segments and final grading."""

from collections.abc import Mapping
from typing import Any


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if arguments["label"] != "safe":
        raise ValueError("Rejected Tool call executed")
    return {"label": "safe", "invocation": 1, "seed": arguments["seed"]}
