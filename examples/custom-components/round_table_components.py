"""Callable checks and Tools for native model Agents."""

from collections.abc import Mapping
from typing import Any


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"label": arguments["label"]}
