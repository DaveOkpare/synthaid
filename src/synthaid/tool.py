"""Tools an agent can offer to a model."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai.types.chat import ChatCompletionFunctionToolParam

from synthaid.message import Message, ToolCall


@dataclass(frozen=True)
class Tool:
    """A function the model can ask to run.

    Attributes:
        name: The name the model uses to call the tool.
        description: What the tool does, written for the model.
        parameters: A JSON schema for the tool's arguments.
        function: The Python function that does the work.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[..., Any]

    def __call__(self, call: ToolCall) -> Message:
        """Run the tool for one call and return its result Message.

        Calls `function(**call.arguments)` and returns
        `Message(role="tool", content=<result as text>, tool_call_id=call.id)`.
        A result that is not a string is turned into JSON.
        """
        result = self.function(**call.arguments)
        content = result if isinstance(result, str) else json.dumps(result)
        return Message("tool", content, tool_call_id=call.id)

    def to_chat_completions(self) -> ChatCompletionFunctionToolParam:
        """This tool as a Chat Completions function tool dict:
        `{"type": "function", "function": {"name", "description", "parameters"}}`.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
