"""Test doubles shared by the test modules."""

from collections.abc import Sequence
import dataclasses
from typing import override

import pydantic

from synthaid import message
from synthaid import model
from synthaid import tool


@dataclasses.dataclass(frozen=True)
class Request:
    """One request a ScriptedModel received.

    Attributes:
        messages: The messages sent, system message first.
        tools: The tools offered to the model.
        output_type: str for text, or a Pydantic class.
    """

    messages: list[message.Message]
    tools: Sequence[tool.Tool]
    output_type: type[str] | type[pydantic.BaseModel]


@dataclasses.dataclass(frozen=True)
class ScriptedModel(model.Model):
    """A Model that answers from a script instead of a server.

    Attributes:
        replies: The replies still to give, in order.
        requests: Every request received, oldest first.
    """

    replies: list[message.Message] = dataclasses.field(default_factory=list)
    requests: list[Request] = dataclasses.field(default_factory=list)

    @override
    def generate(
        self,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        self.requests.append(Request(list(messages), tools, output_type))
        return self.replies.pop(0)

    def seen(self, index: int) -> list[message.Message]:
        """Returns the messages of request `index`, without the system one."""
        return self.requests[index].messages[1:]


def scripted(*replies: message.Message) -> ScriptedModel:
    """Returns a ScriptedModel that answers with `replies` in order."""
    return ScriptedModel("test-model", "http://localhost", replies=[*replies])
