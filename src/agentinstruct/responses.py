"""Responses wire translation; provider-native items stay inside this adapter."""

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentinstruct.plans import JsonValue, canonical_json, json_value
from agentinstruct.provider_errors import classify_provider_error
from agentinstruct.providers import (
    NamedToolChoice,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ReasoningItem,
    Usage,
)
from agentinstruct.seeds import parse_json
from agentinstruct.traces import FunctionCall, Message, ToolCall, immutable_data


class _WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _Text(_WireModel):
    type: Literal["output_text"]
    text: str


class _Refusal(_WireModel):
    type: Literal["refusal"]
    refusal: str


class _Message(_WireModel):
    type: Literal["message"]
    id: str = Field(min_length=1)
    role: Literal["assistant"]
    status: Literal["completed", "in_progress", "incomplete"]
    content: list[Annotated[_Text | _Refusal, Field(discriminator="type")]]


class _Function(_WireModel):
    type: Literal["function_call"]
    id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: str
    status: Literal["completed", "in_progress", "incomplete"] | None = None


class _Summary(_WireModel):
    type: Literal["summary_text"]
    text: str


class _ReasoningText(_WireModel):
    type: Literal["reasoning_text"]
    text: str


class _Reasoning(_WireModel):
    type: Literal["reasoning"]
    id: str = Field(min_length=1)
    summary: list[_Summary]
    content: list[_ReasoningText] | None = None
    encrypted_content: str | None = None
    status: Literal["completed", "in_progress", "incomplete"] | None = None


class _Details(_WireModel):
    reasoning_tokens: int | None = Field(default=None, ge=0)


class _Usage(_WireModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    output_tokens_details: _Details | None = None


class _Incomplete(_WireModel):
    reason: Literal["max_output_tokens", "content_filter"]


class _Error(_WireModel):
    code: str


class _Response(_WireModel):
    id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    status: Literal[
        "completed", "failed", "in_progress", "cancelled", "queued", "incomplete"
    ]
    output: list[
        Annotated[_Message | _Function | _Reasoning, Field(discriminator="type")]
    ]
    usage: _Usage | None = None
    incomplete_details: _Incomplete | None = None
    error: _Error | None = None
    service_tier: str | None = None


def request_body(request: ProviderRequest) -> dict[str, JsonValue]:
    items: list[JsonValue] = []
    for message in request.messages:
        if message.role == "tool":
            if not message.tool_call_id:
                raise ProviderError("invalid_request")
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": message.content,
                }
            )
            continue
        if message.content or not message.tool_calls:
            items.append({"role": message.role, "content": message.content})
        private_items = tuple(
            item
            for continuation in request.continuations
            if continuation.message == message
            for item in continuation.items
        )
        for index in range(len(message.tool_calls) + 1):
            items.extend(
                _reasoning_input(item)
                for item in private_items
                if item.tool_call_index == index
            )
            if index < len(message.tool_calls):
                call = message.tool_calls[index]
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call.id,
                        "name": call.function.name,
                        "arguments": canonical_json(call.function.arguments),
                    }
                )
    body: dict[str, JsonValue] = {
        "model": request.model,
        "input": items,
        "store": False,
        "stream": False,
    }
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "name": tool.id,
                "description": tool.description,
                "parameters": json_value(tool.input_schema),
                "strict": False,
            }
            for tool in request.tools
        ]
    if request.tool_choice is not None:
        body["tool_choice"] = (
            {"type": "function", "name": request.tool_choice.name}
            if isinstance(request.tool_choice, NamedToolChoice)
            else request.tool_choice
        )
    if request.parallel_tool_calls is not None:
        body["parallel_tool_calls"] = request.parallel_tool_calls
    if request.response_format.type != "text":
        format_: dict[str, JsonValue] = {"type": request.response_format.type}
        if request.response_format.type == "json_schema":
            format_.update(
                name=request.response_format.name,
                schema=json_value(request.response_format.schema),
                strict=request.response_format.strict,
            )
            if request.response_format.description is not None:
                format_["description"] = request.response_format.description
        body["text"] = {"format": format_}
    for name, wire_name in (
        ("temperature", "temperature"),
        ("max_tokens", "max_output_tokens"),
        ("top_p", "top_p"),
    ):
        value = getattr(request.inference, name)
        if value is not None:
            body[wire_name] = value
    if request.reasoning is not None:
        body["reasoning"] = {
            key: value
            for key, value in (
                ("effort", request.reasoning.effort),
                ("summary", request.reasoning.summary),
            )
            if value is not None
        }
    if request.inference.seed is not None:
        raise ProviderError("unsupported_feature")
    return body


def _reasoning_input(item: ReasoningItem) -> JsonValue:
    if not item.id:
        raise ProviderError("invalid_request")
    private: dict[str, JsonValue] = {
        "type": "reasoning",
        "id": item.id,
        "summary": [{"type": "summary_text", "text": text} for text in item.summary],
    }
    if item.encrypted_content is not None:
        private["encrypted_content"] = item.encrypted_content
    if item.text:
        private["content"] = [
            {"type": "reasoning_text", "text": text} for text in item.text
        ]
    return private


def normalize_response(
    raw: JsonValue,
    provider: str,
    request_id: str | None,
    latency: float,
    redact: Callable[[JsonValue], JsonValue],
) -> ProviderResponse:
    outputs = raw.get("output") if isinstance(raw, dict) else None
    if isinstance(outputs, list):
        for output in outputs:
            if isinstance(output, dict) and output.get("type") in {
                "web_search_call",
                "file_search_call",
                "computer_call",
                "mcp_call",
                "mcp_list_tools",
                "mcp_approval_request",
                "code_interpreter_call",
                "image_generation_call",
                "local_shell_call",
                "shell_call",
                "apply_patch_call",
            }:
                raise ProviderError("unsupported_feature", request_id=request_id)
    response = _Response.model_validate(raw)
    if response.status == "failed":
        error = classify_provider_error(
            response.error.code if response.error is not None else None,
            request_id=request_id,
            default_kind="unknown" if response.error is not None else "server",
        )
        error.metadata = immutable_data({**error.metadata, "response_id": response.id})
        raise error
    if response.error is not None:
        raise ValueError("Error on a non-failed response")
    if response.status not in {"completed", "incomplete"}:
        raise ProviderError("incomplete", request_id=request_id)
    text: list[str] = []
    calls: list[ToolCall] = []
    reasoning: list[ReasoningItem] = []
    refused = any(
        isinstance(item, _Message)
        and any(isinstance(content, _Refusal) for content in item.content)
        for item in response.output
    )
    for item in response.output:
        if item.status not in {None, "completed"} and response.status == "completed":
            raise ValueError("Incomplete output item in a complete response")
        if isinstance(item, _Reasoning):
            reasoning.append(
                ReasoningItem(
                    item.id,
                    tuple(part.text for part in item.summary),
                    tuple(part.text for part in item.content or ()),
                    item.encrypted_content,
                    len(calls),
                )
            )
        elif isinstance(item, _Message):
            for content in item.content:
                if isinstance(content, _Refusal):
                    refused = True
                else:
                    text.append(content.text)
        elif not refused and response.status == "completed":
            arguments = redact(parse_json(item.arguments, "Tool arguments"))
            if (
                not isinstance(arguments, dict)
                or not item.call_id.strip()
                or not item.name.strip()
            ):
                raise ValueError("Malformed function call")
            calls.append(
                ToolCall(
                    item.call_id, FunctionCall(item.name, immutable_data(arguments))
                )
            )
    if len({item.id for item in response.output}) != len(response.output):
        raise ValueError("Duplicate output item identifier")
    if len({call.id for call in calls}) != len(calls):
        raise ValueError("Duplicate Tool call identifier")
    if not text and not calls and not refused and response.status == "completed":
        raise ValueError("Missing assistant content")
    usage = response.usage
    return ProviderResponse(
        Message("assistant", "".join(text), tool_calls=tuple(calls)),
        (
            "content_filter"
            if response.incomplete_details
            and response.incomplete_details.reason == "content_filter"
            else "length"
        )
        if response.status == "incomplete"
        else "tool_calls"
        if calls
        else "stop",
        provider,
        response.model,
        Usage(
            usage.input_tokens,
            usage.output_tokens,
            usage.total_tokens,
            usage.output_tokens_details.reasoning_tokens
            if usage.output_tokens_details
            else None,
        )
        if usage
        else Usage(),
        request_id,
        latency,
        refused,
        {
            "response_id": response.id,
            "output_item_ids": tuple(item.id for item in response.output),
            "service_tier": response.service_tier,
        },
        reasoning=tuple(reasoning),
    )
