"""An ordinary callable Tool."""

from collections.abc import Mapping
from typing import Any


async def uppercase(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"text": str(arguments["text"]).upper()}
