"""Reusable Agent settings; proposal, review and effects stay local to each turn."""

import asyncio
import math
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any, Literal, cast
from uuid import uuid4

from pydantic import BaseModel

from agentinstruct.episode import (
    Episode,
    FunctionCall,
    Message,
    ToolCall,
    canonical_json,
    freeze,
    json_data,
    parse_json,
)
from agentinstruct.judge import Judge, Judgment
from agentinstruct.tools import Tool, ToolError, schema_validator


class ModelError(RuntimeError):
    def __init__(self, kind: str, evidence: Mapping[str, Any] | None = None) -> None:
        self.kind, self.evidence = kind, freeze(evidence or {})
        super().__init__(f"Model {kind} failed")


class ReviewExhausted(RuntimeError):
    """No approved replacement remains within the Agent's revision budget."""


@dataclass(frozen=True)
class Agent:
    model: str | None = None
    instruction: str = ""
    tools: Sequence[Tool] = ()
    reviewer: Judge | None = None
    max_revisions: int = 1
    accept_on_revision_exhaustion: bool = False
    client: Any = field(default=None, repr=False, compare=False)
    api: str = "chat_completions"
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning: Mapping[str, Any] | None = None
    output_schema: Any = None
    extra_body: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_settings(self)
        tools = tuple(self.tools)
        if any(not isinstance(tool, Tool) for tool in tools):
            raise ValueError("Agent tools must be Tool instances")
        if len({tool.id for tool in tools}) != len(tools):
            raise ValueError("Duplicate Tool IDs in Agent declaration")
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "extra_body", freeze(self.extra_body))
        if self.reasoning is not None:
            object.__setattr__(self, "reasoning", freeze(self.reasoning))
        if self.output_schema is not None:
            _schema(self.output_schema)
            if not isinstance(self.output_schema, type):
                object.__setattr__(self, "output_schema", freeze(self.output_schema))

    async def generate(
        self,
        history: Sequence[Message],
        *,
        client: Any = None,
        role: str = "assistant",
        instruction: str | None = None,
    ) -> Message | list[Message]:
        borrowed = self.client if self.client is not None else client
        if borrowed is None or not self.model:
            raise ValueError("Model Agent requires an explicit client and model")
        raw, evidence = await _invoke(borrowed, self.api, _request(self, history, role))
        return _validated_response(raw, self.api, self.output_schema, evidence)

    async def turn(
        self,
        episode: Episode,
        *,
        role: str = "assistant",
        instruction: str | None = None,
        client: Any = None,
    ) -> Message:
        invocation = _turn_inputs(self, episode, role, instruction, client)
        active = invocation["instruction"]
        turn_id = uuid4().hex
        history = _history(episode, role, active)
        proposals = await self._propose(episode, history, invocation, turn_id)
        return await self._drain(episode, deque(proposals), invocation, turn_id)

    async def _drain(
        self,
        episode: Episode,
        queue: deque[Message],
        invocation: Mapping[str, Any],
        turn_id: str,
    ) -> Message:
        while queue:
            accepted = await self._reviewed(episode, queue.popleft(), queue, invocation)
            last = self._accept(episode, accepted, invocation["role"], turn_id)
            if last.control == "complete":
                return last
            if last.tool_calls:
                await self._execute_tools(episode, last)
                history = _history(
                    episode, invocation["role"], invocation["instruction"]
                )
                queue.extend(await self._propose(episode, history, invocation, turn_id))
        return last

    async def _propose(
        self,
        episode: Episode,
        history: Sequence[Message],
        invocation: Mapping[str, Any],
        turn_id: str,
    ) -> list[Message]:
        try:
            value = await self.generate(history, **invocation)
            return _proposals(episode, value, invocation["role"], turn_id)
        except (Exception, asyncio.CancelledError) as exc:
            _record_failure(episode, exc, "agent_generate", invocation["role"], turn_id)
            raise

    async def _reviewed(
        self,
        episode: Episode,
        message: Message,
        queue: deque[Message],
        invocation: Mapping[str, Any],
    ) -> Message:
        role = invocation["role"]
        context = {"actor_id": role, "turn_id": message.turn_id}
        for revision in range(self.max_revisions + 1):
            self._validate_proposal(episode, message, queue, role)
            episode.record("proposal", **context, message=message, revision=revision)
            judgment = await self._review(episode, message, invocation)
            if judgment is None or judgment.passed:
                return message
            if revision == self.max_revisions:
                return self._exhausted(episode, message, role, message.turn_id or "")
            message = await self._revise(episode, message, judgment, queue, invocation)
        raise AssertionError("Revision loop must accept or exhaust")

    async def _revise(
        self,
        episode: Episode,
        message: Message,
        judgment: Judgment,
        queue: deque[Message],
        invocation: Mapping[str, Any],
    ) -> Message:
        history = _revision_history(episode, message, judgment, invocation)
        replacements = await self._propose(
            episode, history, invocation, message.turn_id or ""
        )
        episode.record("revision", **_revision_link(message, replacements[0]))
        queue.extendleft(reversed(replacements[1:]))
        return replacements[0]

    async def _review(
        self,
        episode: Episode,
        message: Message,
        invocation: Mapping[str, Any],
    ) -> Judgment | None:
        if self.reviewer is None:
            return None
        role = invocation["role"]
        history = (*_history(episode, role, invocation["instruction"]), message)
        try:
            result = await self.reviewer.evaluate(history)
        except (Exception, asyncio.CancelledError) as exc:
            _record_failure(episode, exc, "reviewer", role, message.turn_id)
            raise
        episode.record("review_result", **_judgment_event(result, message))
        return result

    def _exhausted(
        self, episode: Episode, message: Message, role: str, turn_id: str
    ) -> Message:
        fallback = (
            self.accept_on_revision_exhaustion
            and not message.tool_calls
            and message.control is None
        )
        episode.record(
            "review_exhausted",
            actor_id=role,
            turn_id=turn_id,
            accepted=fallback,
            message_id=message.id,
        )
        if not fallback:
            raise ReviewExhausted("Reviewer revisions exhausted")
        return message

    def _validate_proposal(
        self, episode: Episode, message: Message, queue: deque[Message], role: str
    ) -> None:
        if message.role not in {"assistant", "user"} or message.tool_call_id:
            raise ValueError("Only participant messages may be proposed")
        if message.tool_calls and (queue or message.control):
            raise ValueError("Tool proposal must be final, without completion")
        if message.control and (role != "assistant" or queue):
            raise ValueError("Only assistant may complete with the final proposal")
        _call_ids(episode, message, role)
        _validate_output(message, self.output_schema)

    def _accept(
        self, episode: Episode, message: Message, role: str, turn_id: str
    ) -> Message:
        assigned = {tool.id: tool for tool in self.tools}
        for call in message.tool_calls:
            if call.function.name not in assigned:
                raise ToolError("assignment")
            assigned[call.function.name].validate(call.function.arguments)
        return episode.append(
            replace(
                message,
                role=cast(Literal["assistant", "user"], role),
                actor_id=role,
                turn_id=turn_id,
                evidence={},
                visibility="private" if message.tool_calls else "shared",
            )
        )

    async def _execute_tools(self, episode: Episode, message: Message) -> None:
        assigned = {tool.id: tool for tool in self.tools}
        for call in message.tool_calls:
            episode.record(
                "tool_started",
                actor_id=message.actor_id,
                turn_id=message.turn_id,
                message_id=message.id,
                tool_call_id=call.id,
            )
            tool = assigned[call.function.name]
            try:
                result = await tool.call(call.function.arguments)
                _tool_result(episode, message, call, tool, result)
            except (Exception, asyncio.CancelledError) as exc:
                _record_failure(episode, exc, "tool", message.actor_id, message.turn_id)
                raise

    def declaration(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "base_instruction": self.instruction,
            "api": self.api,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "reasoning": self.reasoning,
            "output_schema": _schema(self.output_schema)
            if self.output_schema is not None
            else None,
            "extra_body": self.extra_body,
            "accept_on_revision_exhaustion": self.accept_on_revision_exhaustion,
            "tools": [tool.declaration() for tool in self.tools],
            "max_revisions": self.max_revisions,
            "reviewer": self.reviewer.declaration() if self.reviewer else None,
        }


def _validate_settings(agent: Agent) -> None:
    if not isinstance(agent.instruction, str) or (
        agent.model is not None and not isinstance(agent.model, str)
    ):
        raise ValueError("Agent needs text instruction and an optional model name")
    if type(agent.max_revisions) is not int or agent.max_revisions < 0:
        raise ValueError("Agent max_revisions must be a nonnegative integer")
    if type(agent.accept_on_revision_exhaustion) is not bool:
        raise ValueError("Agent exhaustion fallback must be Boolean")
    if agent.reviewer is not None and not isinstance(agent.reviewer, Judge):
        raise ValueError("Agent reviewer must be a Judge")
    _model_settings(agent)


def _history(episode: Episode, role: str, instruction: str) -> tuple[Message, ...]:
    context: tuple[Message, ...] = (Message("system", instruction),)
    if episode.metadata.get("variables"):
        context += (Message("user", canonical_json(episode.metadata["variables"])),)
    return (*context, *episode.history(role))


def _record_failure(
    episode: Episode,
    error: BaseException,
    stage: str,
    role: str | None,
    turn_id: str | None,
) -> None:
    try:
        episode.record(
            stage + "_error",
            actor_id=role,
            turn_id=turn_id,
            failure=episode.failure(error, stage),
            model_call=getattr(error, "evidence", {}),
        )
    except (OSError, RuntimeError):
        if not isinstance(error, asyncio.CancelledError):
            raise


def _wire_message(message: Message, role: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "role": _wire_role(message, role),
        "content": message.content,
    }
    if message.name:
        data["name"] = message.name
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        data["tool_calls"] = [
            {"id": call.id, "type": "function", "function": _wire_function(call)}
            for call in message.tool_calls
        ]
    return data


def _wire_role(message: Message, role: str) -> str:
    if message.role in {"tool", "system"}:
        return message.role
    if message.actor_id is not None:
        return "assistant" if message.actor_id == role else "user"
    return message.role


def _wire_function(call: ToolCall) -> dict[str, str]:
    return {
        "name": call.function.name,
        "arguments": canonical_json(call.function.arguments),
    }


def _request(agent: Agent, history: Sequence[Message], role: str) -> dict[str, Any]:
    body: dict[str, Any] = {"model": agent.model, "store": False, "stream": False}
    if agent.api == "responses":
        body["input"] = [
            item for message in history for item in _response_input(message, role)
        ]
    else:
        body.update(messages=[_wire_message(message, role) for message in history], n=1)
    if agent.tools:
        body["tools"] = [_wire_tool(tool, agent.api) for tool in agent.tools]
        body["tool_choice"] = "auto"
    _request_options(body, agent)
    reserved = _REQUEST_RESERVED
    if set(agent.extra_body).intersection(set(body) | reserved):
        raise ModelError("invalid_request")
    body["extra_body"] = json_data(agent.extra_body)
    return body


def _wire_tool(tool: Tool, api: str) -> dict[str, Any]:
    data = {
        "name": tool.id,
        "description": tool.description,
        "parameters": json_data(tool.input_schema),
    }
    return (
        {"type": "function", **data, "strict": False}
        if api == "responses"
        else {"type": "function", "function": data}
    )


def _response_input(message: Message, role: str) -> list[dict[str, Any]]:
    if message.role == "tool":
        return [
            dict(
                type="function_call_output",
                call_id=message.tool_call_id,
                output=message.content,
            )
        ]
    items = (
        [{"role": _wire_role(message, role), "content": message.content}]
        if message.content or not message.tool_calls
        else []
    )
    return [*items, *_response_calls(message)]


def _request_options(body: dict[str, Any], agent: Agent) -> None:
    responses = agent.api == "responses"
    if agent.temperature is not None:
        body["temperature"] = agent.temperature
    if agent.max_tokens is not None:
        body["max_output_tokens" if responses else "max_completion_tokens"] = (
            agent.max_tokens
        )
    if agent.reasoning:
        if not responses and set(agent.reasoning) - {"effort"}:
            raise ModelError("unsupported_feature")
        body["reasoning" if responses else "reasoning_effort"] = (
            json_data(agent.reasoning) if responses else agent.reasoning["effort"]
        )
    if agent.output_schema is not None:
        body.update(_output_format(agent.output_schema, responses))


def _output_format(output: Any, responses: bool) -> dict[str, Any]:
    format_ = {"name": "Output", "schema": _schema(output), "strict": True}
    return (
        {"text": {"format": {"type": "json_schema", **format_}}}
        if responses
        else {"response_format": {"type": "json_schema", "json_schema": format_}}
    )


async def _invoke(
    client: Any, api: str, body: dict[str, Any]
) -> tuple[Any, dict[str, Any]]:
    started = monotonic()
    borrowed = (
        client.with_options(max_retries=0)
        if hasattr(client, "with_options")
        else client
    )
    try:
        endpoint = (
            borrowed.responses if api == "responses" else borrowed.chat.completions
        )
        raw = await endpoint.create(**body)
    except Exception as exc:
        raise _model_error(exc) from None
    return raw, _call_evidence(raw, api, body, monotonic() - started)


def _call_evidence(
    raw: Any, api: str, body: dict[str, Any], latency: float
) -> dict[str, Any]:
    history = body.get("input", body.get("messages", []))
    return {
        "api": api,
        "requested_model": body["model"],
        "model": getattr(raw, "model", None),
        "request_id": getattr(raw, "_request_id", None),
        "response_id": getattr(raw, "id", None),
        "latency_seconds": latency,
        "usage": raw.usage.model_dump() if getattr(raw, "usage", None) else {},
        "instructions": history[0] if history else None,
        "reasoning": _reasoning_evidence(raw, api),
    }


def _model_error(error: Exception) -> ModelError:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        kind = _STATUS_KINDS.get(
            status, "server" if status >= 500 else "invalid_request"
        )
    elif "Timeout" in type(error).__name__:
        kind = "timeout"
    elif "Connection" in type(error).__name__:
        kind = "network"
    else:
        kind = "unknown"
    return ModelError(
        kind, {"status_code": status, "request_id": getattr(error, "request_id", None)}
    )


def _response(raw: Any, api: str) -> Message:
    from openai.types.chat import ChatCompletion
    from openai.types.responses import Response

    validated = (Response if api == "responses" else ChatCompletion).model_validate(
        raw.model_dump(), strict=True
    )
    return (
        _responses_proposal(validated)
        if api == "responses"
        else _chat_proposal(validated)
    )


def _chat_proposal(raw: Any) -> Message:
    if len(raw.choices) != 1:
        raise ModelError("malformed_response")
    choice = raw.choices[0]
    if choice.message.refusal:
        raise ModelError("refusal")
    if choice.finish_reason in {"length", "content_filter"}:
        raise ModelError("incomplete")
    calls = tuple(
        _function_call(call.id, call.function.name, call.function.arguments)
        for call in choice.message.tool_calls or ()
    )
    if choice.finish_reason not in {"stop", "tool_calls"} or (
        choice.finish_reason == "tool_calls"
    ) != bool(calls):
        raise ModelError("malformed_response")
    if choice.message.content is None and not calls:
        raise ModelError("malformed_response")
    return Message("assistant", choice.message.content or "", tool_calls=calls)


def _responses_proposal(raw: Any) -> Message:
    _response_items(raw)
    text = _response_text(raw.output)
    calls = tuple(
        _function_call(item.call_id, item.name, item.arguments)
        for item in raw.output
        if item.type == "function_call"
    )
    if not text and not calls:
        raise ModelError("malformed_response")
    return Message(
        "assistant",
        text,
        tool_calls=calls,
        reasoning=_continuation(raw.output) if calls else (),
    )


def _response_items(raw: Any) -> None:
    if raw.error:
        kinds = {"server_error": "server", "rate_limit_exceeded": "rate_limit"}
        raise ModelError(kinds.get(raw.error.code, "unknown"))
    if raw.status != "completed":
        raise ModelError("incomplete")
    if any(
        item.type not in {"message", "function_call", "reasoning"}
        for item in raw.output
    ):
        raise ModelError("unsupported_feature")
    if len({item.id for item in raw.output}) != len(raw.output):
        raise ModelError("malformed_response")
    if any(
        getattr(item, "status", None) not in {None, "completed"} for item in raw.output
    ):
        raise ModelError("malformed_response")


def _response_text(items: Sequence[Any]) -> str:
    parts = [part for item in items if item.type == "message" for part in item.content]
    if any(part.type == "refusal" for part in parts):
        raise ModelError("refusal")
    if any(part.type != "output_text" for part in parts):
        raise ModelError("malformed_response")
    return "".join(part.text for part in parts)


def _function_call(identifier: str, name: str, arguments: str) -> ToolCall:
    return ToolCall(identifier, FunctionCall(name, parse_json(arguments)))


def _continuation(items: Sequence[Any]) -> tuple[Mapping[str, Any], ...]:
    result: list[Mapping[str, Any]] = []
    count = 0
    for item in items:
        if item.type == "function_call":
            count += 1
        if item.type == "reasoning":
            result.append(
                {**item.model_dump(exclude_none=True), "tool_call_index": count}
            )
    return tuple(result)


def _reasoning_evidence(raw: Any, api: str) -> dict[str, Any]:
    if api == "responses":
        return {
            "items": [
                item.model_dump(exclude_none=True)
                for item in getattr(raw, "output", ())
                if item.type == "reasoning"
            ]
        }
    choices = getattr(raw, "choices", ())
    message = choices[0].message if choices else None
    return {
        "text": getattr(message, "reasoning", None)
        or getattr(message, "reasoning_content", None)
    }


def _schema(output: Any) -> dict[str, Any]:
    typed = isinstance(output, type) and issubclass(output, BaseModel)
    data = output.model_json_schema(by_alias=True) if typed else json_data(output)
    if not isinstance(data, dict):
        raise ValueError("Structured output needs an object schema")
    _schema_nodes(data, data, typed)
    root = _schema_reference(data, data["$ref"]) if "$ref" in data else data
    if root.get("type") != "object" or "anyOf" in root:
        raise ValueError("Structured output root must be an object")
    schema_validator(data)
    _schema_limits(data)
    return dict(data)


def _schema_nodes(node: Any, root: Mapping[str, Any], typed: bool = False) -> None:
    if not isinstance(node, dict):
        raise ValueError("Structured schema nodes must be objects")
    if typed:
        node.pop("default", None)
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
            node["required"] = list(node.get("properties", {}))
    _schema_node(node, root)
    for child in _schema_children(node):
        _schema_nodes(child, root, typed)


def _schema_reference(root: Mapping[str, Any], reference: Any) -> Any:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ValueError("Structured schemas require local references")
    value: Any = root
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(value, dict):
        raise ValueError("Reference must resolve to an object schema")
    return value


def _schema_children(node: Mapping[str, Any], *, definitions: bool = True) -> list[Any]:
    keys = ("properties", "$defs") if definitions else ("properties",)
    children = [child for key in keys for child in node.get(key, {}).values()]
    children.extend(node.get("anyOf", []))
    if "items" in node:
        children.append(node["items"])
    return children


def _schema_node(node: Mapping[str, Any], root: Mapping[str, Any]) -> None:
    if set(node) - _SCHEMA_KEYWORDS or not {"type", "anyOf", "$ref"}.intersection(node):
        raise ValueError("Unsupported strict schema keyword or type")
    if "$ref" in node:
        _schema_reference(root, node["$ref"])
    types = node.get("type", [])
    types = types if isinstance(types, list) else [types]
    if "object" in types and (
        node.get("additionalProperties") is not False
        or set(node.get("required", ())) != set(node.get("properties", {}))
    ):
        raise ValueError("Strict objects require every property and forbid extras")
    if "array" in types and not isinstance(node.get("items"), dict):
        raise ValueError("Strict arrays require an item schema")
    _schema_strings(node)


def _schema_strings(node: Mapping[str, Any]) -> None:
    import re

    if "pattern" in node:
        re.compile(node["pattern"])
    if "format" in node and node["format"] not in _SCHEMA_FORMATS:
        raise ValueError("Unsupported string format")
    values = node.get("enum", [])
    if len(values) > 250 and sum(len(v) for v in values if isinstance(v, str)) > 15000:
        raise ValueError("Enum size limit")


def _schema_limits(root: Mapping[str, Any]) -> None:
    nodes = [root]
    for node in nodes:
        nodes.extend(_schema_children(node))
    if sum(len(node.get("properties", {})) for node in nodes) > 5000:
        raise ValueError("Schema property limit")
    if sum(len(node.get("enum", [])) for node in nodes) > 1000:
        raise ValueError("Schema enum limit")
    if sum(_schema_text_size(node) for node in nodes) > 120000:
        raise ValueError("Schema text limit")
    _schema_depth(root, root, 0, frozenset())


def _schema_depth(
    node: Mapping[str, Any], root: Mapping[str, Any], level: int, seen: frozenset[str]
) -> None:
    reference = node.get("$ref")
    if reference is not None and reference not in seen:
        _schema_depth(
            _schema_reference(root, reference), root, level, seen | {reference}
        )
    types = node.get("type", [])
    types = types if isinstance(types, list) else [types]
    level += int("object" in types or "array" in types)
    if level > 10:
        raise ValueError("Schema depth limit")
    for child in _schema_children(node, definitions=False):
        _schema_depth(child, root, level, seen)


def _validate_output(message: Message, output: Any) -> None:
    if output is None:
        return
    if message.tool_calls:
        raise ModelError("schema_mismatch")
    try:
        value = parse_json(message.content)
    except ValueError:
        raise ModelError("invalid_json") from None
    try:
        schema_validator(_schema(output)).validate(value)
        if isinstance(output, type) and issubclass(output, BaseModel):
            output.model_validate_json(message.content, strict=True)
    except Exception:
        raise ModelError("schema_mismatch") from None


def _proposals(episode: Episode, value: Any, role: str, turn_id: str) -> list[Message]:
    proposals = value if isinstance(value, list) else [value]
    if not proposals or any(not isinstance(item, Message) for item in proposals):
        raise ValueError("Agent must return one Message or a nonempty list")
    result = [_safe_proposal(episode, item, role, turn_id) for item in proposals]
    for message in result:
        if message.evidence:
            episode.record(
                "model_call", actor_id=role, turn_id=turn_id, **dict(message.evidence)
            )
    return result


def _safe_proposal(
    episode: Episode, message: Message, role: str, turn_id: str
) -> Message:
    calls = tuple(
        ToolCall(
            call.id,
            FunctionCall(call.function.name, episode.sanitize(call.function.arguments)),
        )
        for call in message.tool_calls
    )
    return replace(
        message,
        id=uuid4().hex,
        actor_id=role,
        turn_id=turn_id,
        tool_calls=calls,
        content=episode.sanitize(message.content),
        reasoning=episode.sanitize(message.reasoning),
    )


def _call_ids(episode: Episode, message: Message, role: str) -> None:
    ids = [call.id for call in message.tool_calls]
    prior = {
        call.id
        for item in episode.messages
        if item.actor_id == role
        for call in item.tool_calls
    }
    if len(ids) != len(set(ids)) or prior.intersection(ids):
        raise ValueError("Tool call identifiers must be unique per Agent")


def _tool_result(
    episode: Episode, message: Message, call: ToolCall, tool: Tool, value: Any
) -> None:
    result = episode.sanitize(value)
    if not _execution_error_result(tool, result):
        result = tool.validate_result(result)
    reply = Message(
        "tool",
        canonical_json(result),
        actor_id=message.actor_id,
        tool_call_id=call.id,
        visibility="private",
        turn_id=message.turn_id,
    )
    episode.append(reply)


_STATUS_KINDS = {
    401: "authentication",
    403: "authorization",
    429: "rate_limit",
    408: "timeout",
    504: "timeout",
}
_SCHEMA_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "$defs",
    "$ref",
    "title",
    "description",
    "enum",
    "const",
    "anyOf",
    "items",
    "pattern",
    "format",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
    "$schema",
}
_SCHEMA_FORMATS = {
    "date-time",
    "time",
    "date",
    "duration",
    "email",
    "hostname",
    "ipv4",
    "ipv6",
    "uuid",
}


def _schema_text_size(node: Mapping[str, Any]) -> int:
    values = [
        *node.get("properties", {}),
        *node.get("$defs", {}),
        *node.get("enum", []),
        node.get("const", ""),
    ]
    return sum(len(value) for value in values if isinstance(value, str))


def _reasoning_at(message: Message, index: int) -> list[dict[str, Any]]:
    return [
        {
            key: json_data(value)
            for key, value in item.items()
            if key != "tool_call_index"
        }
        for item in message.reasoning
        if item.get("tool_call_index", 0) == index
    ]


def _model_settings(agent: Agent) -> None:
    if agent.api not in {"chat_completions", "responses"}:
        raise ValueError("Unsupported model API")
    if agent.temperature is not None and (
        isinstance(agent.temperature, bool) or not math.isfinite(agent.temperature)
    ):
        raise ValueError("Temperature must be finite")
    if agent.max_tokens is not None and (
        type(agent.max_tokens) is not int or agent.max_tokens < 1
    ):
        raise ValueError("max_tokens must be a positive integer")


def _validated_response(
    raw: Any, api: str, output: Any, evidence: Mapping[str, Any]
) -> Message:
    try:
        proposal = _response(raw, api)
        _validate_output(proposal, output)
        ids = [call.id for call in proposal.tool_calls]
        if len(ids) != len(set(ids)):
            raise ModelError("malformed_response")
        return replace(proposal, evidence=evidence)
    except ModelError as exc:
        raise ModelError(exc.kind, evidence) from None
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ModelError("malformed_response", evidence) from exc


def _judgment_event(result: Judgment, message: Message) -> dict[str, Any]:
    return dict(
        accepted=result.passed,
        feedback=result.feedback,
        criteria=result.criteria,
        score=result.score,
        model_call=result.evidence,
        actor_id=message.actor_id,
        turn_id=message.turn_id,
        message_id=message.id,
    )


def _revision_history(
    episode: Episode,
    message: Message,
    judgment: Judgment,
    invocation: Mapping[str, Any],
) -> tuple[Message, ...]:
    context = _history(episode, invocation["role"], invocation["instruction"])
    feedback = "Private review feedback:\n" + episode.sanitize(judgment.feedback)
    return (*context, message, Message("user", feedback))


def _turn_inputs(
    agent: Agent, episode: Episode, role: str, instruction: str | None, client: Any
) -> dict[str, Any]:
    episode.require_open()
    if role not in {"assistant", "user"}:
        raise ValueError("Unsupported participant role")
    active = agent.instruction if instruction is None else instruction
    if not isinstance(active, str):
        raise ValueError("Active instruction must be text")
    reviewer_client = agent.reviewer.client if agent.reviewer else None
    episode.add_secrets(agent.client, client, reviewer_client)
    return {"role": role, "instruction": active, "client": client}


def _revision_link(original: Message, replacement: Message) -> dict[str, Any]:
    return {
        "actor_id": original.actor_id,
        "turn_id": original.turn_id,
        "revises_message_id": original.id,
        "message_id": replacement.id,
    }


def _response_calls(message: Message) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index in range(len(message.tool_calls) + 1):
        items.extend(_reasoning_at(message, index))
        if index < len(message.tool_calls):
            call = message.tool_calls[index]
            items.append(
                dict(type="function_call", call_id=call.id, **_wire_function(call))
            )
    return items


_REQUEST_RESERVED = {
    "model",
    "input",
    "messages",
    "store",
    "stream",
    "tools",
    "tool_choice",
    "previous_response_id",
    "conversation",
    "n",
    "instructions",
    "background",
}


def _execution_error_result(tool: Tool, result: Any) -> bool:
    if (
        tool.execution_errors != "result"
        or not isinstance(result, dict)
        or set(result) != {"error"}
    ):
        return False
    error = result["error"]
    return (
        isinstance(error, dict)
        and set(error) == {"exception", "kind"}
        and isinstance(error["exception"], str)
        and error["kind"] == "execution"
    )
