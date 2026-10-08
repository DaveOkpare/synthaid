"""One call to a Chat Completions server."""

from collections.abc import Sequence
import dataclasses
import functools

import openai
import pydantic

from synthaid import message
from synthaid import tool


@dataclasses.dataclass(frozen=True)
class Model:
    """A model on a server that speaks Chat Completions.

    A Model is immutable, so one instance can be shared by many agents.

    Attributes:
        model_name: The model id on the server.
        base_url: The server's base URL.
        api_key: The API key. None lets the openai SDK read OPENAI_API_KEY.
        temperature: The sampling temperature for every call.
    """

    model_name: str
    base_url: str
    api_key: str | None = None
    temperature: float = 0.7

    def generate(
        self,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        """Sends one request and returns the model's reply.

        Makes exactly one request. It never runs tools and never retries
        beyond the openai SDK's own retries. The caller adds any system
        message.

        With a BaseModel `output_type` the request goes through
        `client.chat.completions.parse()` and the reply's content is a
        validated instance. `tools` must be empty in that case. Otherwise
        the request goes through `client.chat.completions.create()` and
        the reply's content is text, or None when the model only asked
        for tools.

        Args:
            messages: The conversation so far.
            tools: The tools the model may ask to run.
            output_type: str for text, or a Pydantic class for structured
                output.

        Returns:
            An assistant Message with content, tool calls and reasoning.

        Raises:
            pydantic.ValidationError: The structured reply did not match
                `output_type`.
            openai.LengthFinishReasonError: The structured reply was cut
                off.
            openai.ContentFilterFinishReasonError: The server filtered the
                structured reply.
            json.JSONDecodeError: A tool call's arguments were not valid
                JSON.
            openai.APIError: Any transport or server error.
        """
        wire_messages = [item.to_chat_completions() for item in messages]
        if issubclass(output_type, pydantic.BaseModel):
            if tools:
                raise ValueError("tools cannot be used with structured output")
            parsed = self._client.chat.completions.parse(
                model=self.model_name,
                messages=wire_messages,
                temperature=self.temperature,
                response_format=output_type,
            )
            parsed_reply = parsed.choices[0].message
            return message.Message.from_chat_completions(parsed_reply)
        wire_tools = [item.to_chat_completions() for item in tools]
        completion = self._client.chat.completions.create(
            model=self.model_name,
            messages=wire_messages,
            temperature=self.temperature,
            tools=wire_tools or openai.omit,
        )
        reply = completion.choices[0].message
        return message.Message.from_chat_completions(reply)

    @functools.cached_property
    def _client(self) -> openai.OpenAI:
        """The openai client, created on first use and then reused."""
        return openai.OpenAI(base_url=self.base_url, api_key=self.api_key)
