"""Tools an agent can offer to a model."""

from collections.abc import Callable
import dataclasses
import json
from typing import Any

from openai.types import chat

from synthaid import message


@dataclasses.dataclass(frozen=True)
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

    def __call__(self, call: message.ToolCall) -> message.Message:
        """Runs the tool for one call and returns its result Message.

        Args:
            call: The tool call from the model. Its arguments are passed to
                `function` as keyword arguments.

        Returns:
            A tool Message with the result as text and `tool_call_id` set
            to `call.id`. A result that is not a string is turned into JSON.
        """
        result = self.function(**call.arguments)
        content = result if isinstance(result, str) else json.dumps(result)
        return message.Message("tool", content, tool_call_id=call.id)

    def to_chat_completions(self) -> chat.ChatCompletionFunctionToolParam:
        """Returns this tool as a Chat Completions function tool dict."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
