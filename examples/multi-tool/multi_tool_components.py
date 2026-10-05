"""Ordered Tool calls with a declared execution error result."""

from collections.abc import Mapping
from typing import Any


async def summarize(arguments: Mapping[str, Any]) -> dict[str, Any]:
    text = str(arguments["text"])
    if text == "missing":
        raise ValueError("The offline fixture deliberately simulates a failure")
    return {"summary": text.upper()}
