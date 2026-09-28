"""Framework-owned inference contract and stateless Chat Completions transport.

HTTPX is imported only when a Provider generates or closes a live client. Its
transport is a public injection seam; no vendor response crosses this module.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentinstruct.plans import (
    FrozenJsonValue,
    JsonSchema,
    JsonValue,
    ProviderPlan,
    ToolPlan,
    canonical_json,
    freeze,
    json_value,
)
from agentinstruct.traces import FunctionCall, Message, ToolCall, immutable_data

if TYPE_CHECKING:
    import httpx

type ProviderErrorKind = Literal[
    "authentication",
    "authorization",
    "rate_limit",
    "timeout",
    "network",
    "invalid_request",
    "unsupported_feature",
    "model_unavailable",
    "server",
    "malformed_response",
    "unknown",
    "refusal",
    "incomplete",
]
type ToolChoiceMode = Literal["none", "auto", "required", "named"]
type ResponseFormatMode = Literal["text", "json_object", "json_schema"]
type FinishState = Literal["stop", "tool_calls", "length", "content_filter"]


class ProviderError(Exception):
    """A classified failure containing only framework-approved diagnostic data."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        code: str | None = None,
    ) -> None:
        self.kind = kind
        self.metadata = immutable_data(
            {
                "status_code": status_code,
                "request_id": request_id,
                "code": code,
            }
        )
        super().__init__(f"Provider failure: {kind}")


@dataclass(frozen=True)
class SurfaceCapabilities:
    text: bool = True
    function_tools: bool = True
    tool_choices: frozenset[ToolChoiceMode] = frozenset(
        {"none", "auto", "required", "named"}
    )
    parallel_tool_calls: bool = True
    response_formats: frozenset[ResponseFormatMode] = frozenset(
        {"text", "json_object", "json_schema"}
    )
    pydantic_round_trip: bool = False
    reasoning: bool = False
    reasoning_controls: frozenset[str] = frozenset()
    native_extensions: frozenset[str] = frozenset()
    multimodal: bool = False
    endpoint_preflight: bool = False
    streaming: bool = False

    def __post_init__(self) -> None:
        for name in (
            "tool_choices",
            "response_formats",
            "reasoning_controls",
            "native_extensions",
        ):
            object.__setattr__(self, name, frozenset(getattr(self, name)))


@dataclass(frozen=True)
class ProviderCapabilities:
    surfaces: Mapping[str, SurfaceCapabilities]

    def __post_init__(self) -> None:
        object.__setattr__(self, "surfaces", MappingProxyType(dict(self.surfaces)))

    def require(self, api: str, request: ProviderRequest) -> None:
        profile = self.surfaces.get(api)
        mode = (
            "named"
            if isinstance(request.tool_choice, NamedToolChoice)
            else request.tool_choice
        )
        if (
            profile is None
            or not profile.text
            or (request.tools and not profile.function_tools)
            or (mode is not None and mode not in profile.tool_choices)
            or (request.parallel_tool_calls is True and not profile.parallel_tool_calls)
            or request.response_format.type not in profile.response_formats
        ):
            raise ProviderError("unsupported_feature")


@dataclass(frozen=True)
class NamedToolChoice:
    name: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Named Tool choice requires a function name")


@dataclass(frozen=True)
class ResponseFormat:
    type: ResponseFormatMode = "text"
    name: str = "result"
    schema: JsonSchema | None = None
    strict: bool = True

    def __post_init__(self) -> None:
        if self.type not in {"text", "json_object", "json_schema"}:
            raise ValueError("Unknown response format")
        if (self.type == "json_schema") != (self.schema is not None):
            raise ValueError("JSON Schema response format requires exactly one schema")
        if self.schema is not None:
            object.__setattr__(
                self, "schema", cast(JsonSchema, freeze(json_value(self.schema)))
            )


@dataclass(frozen=True)
class InferenceControls:
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        for name in ("temperature", "top_p"):
            value = getattr(self, name)
            if value is not None and (
                type(value) not in {int, float} or not math.isfinite(value) or value < 0
            ):
                raise ValueError(
                    "Inference sampling controls require finite nonnegative numbers"
                )
        if self.top_p is not None and self.top_p > 1:
            raise ValueError("top_p must be at most 1")
        if self.max_tokens is not None and (
            type(self.max_tokens) is not int or self.max_tokens <= 0
        ):
            raise ValueError("max_tokens must be a positive integer")
        if self.seed is not None and type(self.seed) is not int:
            raise ValueError("seed must be an integer")


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    messages: tuple[Message, ...]
    tools: tuple[ToolPlan, ...] = ()
    tool_choice: Literal["none", "auto", "required"] | NamedToolChoice | None = None
    parallel_tool_calls: bool | None = None
    response_format: ResponseFormat = field(default_factory=ResponseFormat)
    inference: InferenceControls = field(default_factory=InferenceControls)
    metadata: Mapping[str, FrozenJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "metadata", immutable_data(self.metadata))
        if not self.model.strip() or not self.messages:
            raise ValueError("Provider requests require a model and ordered Messages")
        if set(self.metadata) - {
            "run_id",
            "trace_id",
            "actor_id",
            "step_id",
            "turn_id",
        }:
            raise ValueError("Only framework identity metadata is supported")
        if any(
            value is not None and not isinstance(value, str)
            for value in self.metadata.values()
        ):
            raise ValueError("Provider metadata must contain identity strings")
        if isinstance(self.tool_choice, NamedToolChoice):
            if self.tool_choice.name not in {tool.id for tool in self.tools}:
                raise ValueError("Named Tool choice must name a declared Tool")
        elif self.tool_choice not in {None, "none", "auto", "required"}:
            raise ValueError("Unknown Tool choice")
        if not self.tools and self.tool_choice not in {None, "none"}:
            raise ValueError("Tool choice requires declared Tools")


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.prompt_tokens,
            self.completion_tokens,
            self.total_tokens,
            self.reasoning_tokens,
        ):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Usage must contain nonnegative integer counts")


@dataclass(frozen=True)
class ProviderResponse:
    message: Message
    finish_state: FinishState
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    request_id: str | None = None
    latency_seconds: float = 0.0
    refused: bool = False
    metadata: Mapping[str, FrozenJsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", immutable_data(self.metadata))
        if self.message.role != "assistant":
            raise ValueError("Provider responses require one assistant proposal")
        if not math.isfinite(self.latency_seconds) or self.latency_seconds < 0:
            raise ValueError("Provider latency must be finite and nonnegative")


class Provider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...

    async def generate(self, request: ProviderRequest) -> ProviderResponse: ...

    async def aclose(self) -> None: ...


# Strict wire validation rejects booleans as token counts and never passes vendor
# model instances beyond this adapter. Unknown wire metadata is deliberately lost.
class _WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _Function(_WireModel):
    name: str = Field(min_length=1)
    arguments: str


class _Call(_WireModel):
    id: str = Field(min_length=1)
    type: Literal["function"]
    function: _Function


class _Message(_WireModel):
    role: Literal["assistant"]
    content: str | None = None
    tool_calls: list[_Call] | None = None
    refusal: str | None = None


class _Choice(_WireModel):
    index: Literal[0]
    message: _Message
    finish_reason: FinishState


class _Details(_WireModel):
    reasoning_tokens: int | None = Field(default=None, ge=0)


class _Usage(_WireModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    completion_tokens_details: _Details | None = None


class _Completion(_WireModel):
    id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    choices: list[_Choice] = Field(min_length=1, max_length=1)
    usage: _Usage | None = None
    system_fingerprint: str | None = None
    service_tier: str | None = None


class ChatCompletionsProvider:
    """One request, no retries, no remote conversation state or API fallback.

    The optional HTTPX transport transfers ownership to this Provider. Credentials
    are resolved on first inference; construction and capabilities are model-free.
    """

    def __init__(
        self,
        plan: ProviderPlan,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._plan = plan
        self._transport = transport
        self._timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        self._secret: str | None = None
        self._closed = False

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities({"chat_completions": SurfaceCapabilities()})

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        import httpx

        self.capabilities.require(self._plan.api, request)
        if self._closed:
            raise ProviderError("invalid_request")
        started = monotonic()
        try:
            body = _request_body(request)
            if self._client is None:
                key_env = self._plan.api_key_env or (
                    "OPENAI_API_KEY" if self._plan.type == "openai" else None
                )
                self._secret = os.environ.get(key_env) if key_env else None
                if key_env and not self._secret:
                    raise ProviderError("authentication")
                base_url = self._plan.base_url
                if base_url is None:
                    if self._plan.type != "openai":
                        raise ProviderError("invalid_request")
                    base_url = "https://api.openai.com/v1"
                self._client = httpx.AsyncClient(
                    base_url=base_url.rstrip("/") + "/",
                    headers={"Authorization": f"Bearer {self._secret}"}
                    if self._secret
                    else {},
                    transport=self._transport
                    if self._transport is not None
                    else httpx.AsyncHTTPTransport(retries=0),
                    timeout=self._timeout,
                    follow_redirects=False,
                )
            response = await self._client.post("chat/completions", json=body)
            request_id = self._scrub(response.headers.get("x-request-id"))
            if not response.is_success:
                raise _http_error(response, request_id)
            try:
                raw = self._scrub_data(response.json())
                parsed = _Completion.model_validate(raw)
                return _response(
                    parsed,
                    self._plan.id,
                    request_id,
                    monotonic() - started,
                    self._scrub_data,
                )
            except (ValidationError, ValueError, TypeError, KeyError):
                raise ProviderError(
                    "malformed_response", request_id=request_id
                ) from None
        except ProviderError:
            raise
        except httpx.TimeoutException:
            raise ProviderError("timeout") from None
        except httpx.RequestError:
            raise ProviderError("network") from None
        except Exception:
            # Never persist an arbitrary transport exception, URL, headers or body.
            raise ProviderError("unknown") from None

    def _scrub(self, value: str | None) -> str | None:
        return (
            value.replace(self._secret, "[REDACTED]")
            if value and self._secret
            else value
        )

    def _scrub_data(self, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return self._scrub(value)
        if isinstance(value, list):
            return [self._scrub_data(item) for item in value]
        if isinstance(value, dict):
            return {
                cast(str, self._scrub(key)): self._scrub_data(item)
                for key, item in value.items()
            }
        return value

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._client is not None:
                await self._client.aclose()
            elif self._transport is not None:
                await self._transport.aclose()
        except Exception:
            raise ProviderError("unknown") from None
        finally:
            self._secret = None


def create_provider(plan: ProviderPlan) -> Provider:
    if (
        plan.type not in {"openai", "openai-compatible"}
        or plan.api != "chat_completions"
    ):
        raise ProviderError("unsupported_feature")
    return ChatCompletionsProvider(plan)


def _request_body(request: ProviderRequest) -> dict[str, JsonValue]:
    messages: list[JsonValue] = []
    for message in request.messages:
        item: dict[str, JsonValue] = {"role": message.role, "content": message.content}
        if message.name is not None:
            item["name"] = message.name
        if message.tool_call_id is not None:
            item["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": canonical_json(call.function.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        messages.append(item)
    body: dict[str, JsonValue] = {
        "model": request.model,
        "messages": messages,
        "store": False,
        "stream": False,
        "n": 1,
    }
    if request.tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.id,
                    "description": tool.description,
                    "parameters": json_value(tool.input_schema),
                },
            }
            for tool in request.tools
        ]
    if request.tool_choice is not None:
        body["tool_choice"] = (
            {"type": "function", "function": {"name": request.tool_choice.name}}
            if isinstance(request.tool_choice, NamedToolChoice)
            else request.tool_choice
        )
    if request.parallel_tool_calls is not None:
        body["parallel_tool_calls"] = request.parallel_tool_calls
    if request.response_format.type != "text":
        response_format: dict[str, JsonValue] = {"type": request.response_format.type}
        if request.response_format.type == "json_schema":
            response_format["json_schema"] = {
                "name": request.response_format.name,
                "schema": json_value(request.response_format.schema),
                "strict": request.response_format.strict,
            }
        body["response_format"] = response_format
    for name, wire_name in (
        ("temperature", "temperature"),
        ("max_tokens", "max_completion_tokens"),
        ("top_p", "top_p"),
        ("seed", "seed"),
    ):
        value = getattr(request.inference, name)
        if value is not None:
            body[wire_name] = value
    return body


def _response(
    raw: _Completion,
    provider: str,
    request_id: str | None,
    latency: float,
    redact: Callable[[JsonValue], JsonValue],
) -> ProviderResponse:
    choice = raw.choices[0]
    calls: list[ToolCall] = []
    for call in choice.message.tool_calls or ():
        arguments = redact(json.loads(call.function.arguments))
        if (
            not isinstance(arguments, dict)
            or not call.id.strip()
            or not call.function.name.strip()
        ):
            raise ValueError("Malformed function call")
        canonical_json(arguments)  # Reject NaN/infinity, including nested values.
        calls.append(
            ToolCall(
                call.id, FunctionCall(call.function.name, immutable_data(arguments))
            )
        )
    if len({call.id for call in calls}) != len(calls):
        raise ValueError("Duplicate Tool call identifier")
    if (choice.finish_reason == "tool_calls") != bool(calls):
        raise ValueError("Tool calls require an unambiguous complete function proposal")
    if (
        choice.message.content is None
        and not calls
        and choice.message.refusal is None
        and choice.finish_reason == "stop"
    ):
        raise ValueError("Missing assistant content")
    usage = raw.usage
    return ProviderResponse(
        Message("assistant", choice.message.content or "", tool_calls=tuple(calls)),
        choice.finish_reason,
        provider,
        raw.model,
        Usage(
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
            usage.completion_tokens_details.reasoning_tokens
            if usage.completion_tokens_details
            else None,
        )
        if usage
        else Usage(),
        request_id,
        latency,
        choice.message.refusal is not None,
        {
            "response_id": raw.id,
            "system_fingerprint": raw.system_fingerprint,
            "service_tier": raw.service_tier,
        },
    )


def _http_error(response: httpx.Response, request_id: str | None) -> ProviderError:
    code = None
    try:
        raw = response.json()
        candidate = raw.get("error", {}).get("code")
        if candidate in {
            "model_not_found",
            "unsupported_parameter",
            "unsupported_value",
            "unsupported_feature",
        }:
            code = candidate
    except (ValueError, AttributeError, TypeError):
        pass
    status = response.status_code
    kind: ProviderErrorKind
    if status == 401:
        kind = "authentication"
    elif status == 403:
        kind = "authorization"
    elif status == 429:
        kind = "rate_limit"
    elif status in {408, 504}:
        kind = "timeout"
    elif code == "model_not_found":
        kind = "model_unavailable"
    elif code in {"unsupported_parameter", "unsupported_value", "unsupported_feature"}:
        kind = "unsupported_feature"
    elif 400 <= status < 500:
        kind = "invalid_request"
    elif status >= 500:
        kind = "server"
    else:
        kind = "unknown"
    return ProviderError(kind, status_code=status, request_id=request_id, code=code)
