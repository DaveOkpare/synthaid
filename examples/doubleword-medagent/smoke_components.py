"""A read-only capability explicitly closed over each Task's scenario input."""

from collections.abc import Mapping
from typing import Any

from agentinstruct import Tool


def read_scenario(config: Mapping[str, Any]) -> Tool:
    variables = config["variables"]

    async def read(arguments: Mapping[str, Any]) -> dict[str, str]:
        return {
            key: str(variables[key]) for key in ("topic", "discussion_type", "language")
        }

    return Tool(
        read,
        id=config["id"],
        description=config["description"],
        input_schema=config["input_schema"],
        output_schema=config["output_schema"],
    )
