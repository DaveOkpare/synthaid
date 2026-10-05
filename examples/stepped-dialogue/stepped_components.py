"""Ordered segments continue accepted and private history without Agent state."""

from collections.abc import Mapping
from typing import Any


async def lookup(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"greeting": f"Hello, {arguments['name']}."}
