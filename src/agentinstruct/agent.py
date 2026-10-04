"""Generate a sample and optionally revise it from reviewer feedback."""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Protocol

from agentinstruct.episode import FunctionCall, Message, ToolCall
from agentinstruct.judge import Evaluator, Judgment
from agentinstruct.tools import Tool


class Generator(Protocol):
    async def generate(
        self,
        history: Sequence[Message],
        *,
        client: Any = None,
        role: str = "assistant",
        instruction: str | None = None,
    ) -> Message: ...


class ReviewExhausted(RuntimeError):
    """The reviewer rejected the final sample."""


@dataclass(frozen=True)
class Agent:
    model: str | None = None
    instruction: str = ""
    tools: Sequence[Tool] = ()
    reviewer: Evaluator | None = None
    max_revisions: int = 1
    client: Any = field(default=None, repr=False, compare=False)
    generator: Generator | None = field(default=None, repr=False, compare=False)

    async def generate(
        self, history: Sequence[Message], *, client: Any = None, role: str = "assistant"
    ) -> Message:
        if type(self.max_revisions) is not int or self.max_revisions < 0:
            raise ValueError("max_revisions must be a nonnegative integer")
        history = tuple(history)
        if not history or history[0].role != "system":
            history = (Message("system", self.instruction), *history)
        sampling = history
        for _ in range(self.max_revisions + 1):
            draft = await _sample(self, sampling, client, role)
            judgment = await self._review((*history, draft))
            if judgment is None or judgment.passed:
                return draft
            sampling = (*history, draft, Message("user", judgment.feedback))
        raise ReviewExhausted("Reviewer revisions exhausted")

    async def _review(self, history: Sequence[Message]) -> Judgment | None:
        if self.reviewer is None:
            return None
        result = await self.reviewer.evaluate(history)
        if not isinstance(result, Judgment):
            raise ValueError("Reviewer must return a Judgment")
        return result


async def _sample(
    agent: Agent, history: Sequence[Message], client: Any, role: str
) -> Message:
    client = agent.client if agent.client is not None else client
    if agent.generator is None:
        message = await _model_sample(agent, history, client, role)
    else:
        message = await agent.generator.generate(
            history, client=client, role=role, instruction=history[0].content
        )
    if not isinstance(message, Message) or message.role not in {"assistant", "user"}:
        raise ValueError("Agent must return one participant Message")
    return replace(message, actor_id=role)


async def _model_sample(
    agent: Agent, history: Sequence[Message], client: Any, role: str
) -> Message:
    if client is None or not agent.model:
        raise ValueError("Model Agent requires a client and model")
    client = client.with_options(max_retries=0)
    messages = [_chat_message(message, role) for message in history]
    options = dict(model=agent.model, store=False, stream=False)
    if agent.tools:
        options["tools"] = [_model_tool(tool) for tool in agent.tools]
    response = await client.chat.completions.create(messages=messages, **options)
    return _chat_response(response)


def _model_tool(tool: Tool) -> dict[str, Any]:
    function = dict(
        name=tool.id,
        description=tool.description,
        parameters=tool.input_schema,
    )
    return {"type": "function", "function": function}


def _chat_message(message: Message, role: str) -> dict[str, Any]:
    wire_role = message.role
    if message.actor_id is not None and wire_role not in {"system", "tool"}:
        wire_role = "assistant" if message.actor_id == role else "user"
    data: dict[str, Any] = {"role": wire_role, "content": message.content}
    if message.tool_calls:
        data["tool_calls"] = [asdict(call) for call in message.tool_calls]
        for call in data["tool_calls"]:
            function = call["function"]
            function["arguments"] = json.dumps(function["arguments"], allow_nan=False)
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    return data


def _chat_response(response: Any) -> Message:
    choice = response.choices[0]
    if choice.message.refusal or choice.finish_reason not in {"stop", "tool_calls"}:
        raise RuntimeError("Model response did not complete")
    return Message(
        "assistant",
        choice.message.content or "",
        tool_calls=tuple(
            ToolCall(
                call.id,
                FunctionCall(call.function.name, json.loads(call.function.arguments)),
            )
            for call in choice.message.tool_calls or ()
        ),
    )
