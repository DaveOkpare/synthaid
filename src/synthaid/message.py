"""Messages exchanged between agents, models and tools."""

import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from openai.types.chat import (
    ChatCompletionMessage,
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
)
from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    """A request from the model to run one tool.

    Attributes:
        id: The call id the server assigned. The tool result Message
            carries the same id so the two can be matched.
        name: The name of the tool to run.
        arguments: The arguments for the tool, already decoded from JSON.
    """

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """One message in a conversation.

    A single class covers every message type:

    - system, user: `content` is text.
    - assistant: `content` is text, a Pydantic instance (structured
      output), or None when the model only asked for tools. `tool_calls`
      lists those requests. `reasoning` holds the model's reasoning when
      the server returned any.
    - tool: `content` is the tool's result as text and `tool_call_id`
      names the call it answers.

    Reasoning is kept for logs and history but is never sent back to a
    model.
    """

    role: Role
    content: str | BaseModel | None
    reasoning: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    @property
    def text(self) -> str:
        """The content as text.

        Structured content is turned into JSON. Missing content is an
        empty string. Use this whenever content is passed on or stored.
        """
        if isinstance(self.content, BaseModel):
            return self.content.model_dump_json()
        return self.content or ""

    def to_chat_completions(self) -> ChatCompletionMessageParam:
        """This message as a Chat Completions message dict.

        Drops reasoning. Sends structured content as JSON. Tool calls are
        written as `tool_calls` entries of type "function" with the
        arguments as a JSON string. A tool result is written with
        `role="tool"` and its `tool_call_id`.
        """
        wire: dict[str, Any] = {
            "role": self.role,
            "content": None if self.content is None else self.text,
        }
        if self.tool_calls:
            wire["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            wire["tool_call_id"] = self.tool_call_id
        return cast(ChatCompletionMessageParam, wire)

    @classmethod
    def from_chat_completions(cls, message: ChatCompletionMessage) -> "Message":
        """Build an assistant Message from a Chat Completions reply.

        Uses `parsed` as content when present, otherwise `content`. Reads
        reasoning from the `reasoning_content` field when the server sends
        it. Decodes each tool call's arguments from JSON.

        Raises:
            json.JSONDecodeError: a tool call's arguments were not valid
                JSON.
        """
        parsed = getattr(message, "parsed", None)
        extra = message.model_extra or {}
        return cls(
            role="assistant",
            content=parsed if parsed is not None else message.content,
            reasoning=extra.get("reasoning_content"),
            tool_calls=tuple(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    arguments=json.loads(call.function.arguments),
                )
                for call in message.tool_calls or ()
                if isinstance(call, ChatCompletionMessageFunctionToolCall)
            ),
        )
