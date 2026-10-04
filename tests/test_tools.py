"""Tools expose a model schema and invoke the supplied function directly."""

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from agentinstruct import Tool


@pytest.mark.asyncio
async def test_tool_schema_and_function_call() -> None:
    async def uppercase(arguments: Mapping[str, Any]) -> str:
        return str(arguments["text"]).upper()

    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}
    tool = Tool(
        uppercase, id="shout", description="Uppercase text", input_schema=parameters
    )
    assert tool.schema() == {
        "type": "function",
        "function": {
            "name": "shout",
            "description": "Uppercase text",
            "parameters": parameters,
        },
    }
    assert await tool.call({"text": "Hello"}) == "HELLO"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ValueError, asyncio.CancelledError])
async def test_tool_propagates_function_errors(failure: type[BaseException]) -> None:
    error = failure("function failed")

    async def failing(arguments: Mapping[str, Any]) -> Any:
        raise error

    with pytest.raises(failure) as caught:
        await Tool(failing).call({})
    assert caught.value is error
