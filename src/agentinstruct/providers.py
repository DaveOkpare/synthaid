"""Framework-owned inference contract and stateless Chat Completions transport.

HTTPX is imported only when a Provider generates or closes a live client. Its
transport is a public injection seam; no vendor response crosses this module.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from time import monotonic
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentinstruct.plans import (
    FrozenJsonValue,
    JsonSchema,
    JsonValue,
    ProviderPlan,
    ReasoningControls,
    StructuredOutputPlan,
    ToolPlan,
    VllmOptions,
    canonical_json,
    freeze,
    json_value,
)
from agentinstruct.provider_errors import ProviderError as ProviderError
from agentinstruct.provider_errors import (
    StructuredOutputValidationError,
    classify_provider_error,
)
from agentinstruct.seeds import parse_json
from agentinstruct.structured import (
    JsonSchemaSpec,
    StructuredOutput,
    compile_structured_output,
    preflight_structured_output,
    validate_structured_output,
)
from agentinstruct.traces import FunctionCall, Message, ToolCall, immutable_data

if TYPE_CHECKING:
    import httpx

type ToolChoiceMode = Literal["none", "auto", "required", "named"]
type ResponseFormatMode = Literal["text", "json_object", "json_schema"]
type FinishState = Literal["stop", "tool_calls", "length", "content_filter"]


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
            or (
                request.reasoning is not None
                and (
                    (
                        request.reasoning.effort is not None
                        and "effort" not in profile.reasoning_controls
                    )
                    or (
                        request.reasoning.summary is not None
                        and "summary" not in profile.reasoning_controls
                    )
                )
            )
            or (
                request.vllm_options is not None
                and "vllm" not in profile.native_extensions
            )
            or (request.continuations and not profile.reasoning)
            or (
                isinstance(request.structured_output, type)
                and not profile.pydantic_round_trip
            )
        ):
            raise ProviderError("unsupported_feature")
        if request.structured_plan is not None:
            preflight_structured_output(request.structured_plan)


class CompatibleCapabilities(ProviderCapabilities):
    def __init__(self, plan: ProviderPlan) -> None:
        assert plan.endpoint_profile is not None
        object.__setattr__(self, "plan", plan)
        super().__init__(
            {
                api: SurfaceCapabilities(
                    response_formats=frozenset(surface.response_formats),
                    function_tools=bool(surface.tool_choices),
                    tool_choices=frozenset(surface.tool_choices),
                    parallel_tool_calls=surface.parallel_tool_calls,
                    pydantic_round_trip="json_schema" in surface.response_formats,
                    reasoning=surface.reasoning,
                    reasoning_controls=frozenset(surface.reasoning_controls),
                )
                for api, surface in plan.endpoint_profile.surfaces.items()
                if api == "chat_completions" or surface.conformance == "passed"
            }
        )

    plan: ProviderPlan

    def require(self, api: str, request: ProviderRequest) -> None:
        super().require(api, request)
        assert self.plan.endpoint_profile is not None
        profile = self.plan.endpoint_profile
        if profile.model != request.model:
            raise ProviderError("unsupported_feature")
        surface = profile.surfaces[api]
        if api == "chat_completions" and (
            surface.reasoning or (request.reasoning and request.reasoning.summary)
        ):
            raise ProviderError("unsupported_feature")
        features: set[str] = set()
        if surface.reasoning:
            features.add("reasoning")
        if request.tools and request.tool_choice != "none":
            features.add("tools")
        if request.response_format.type != "text":
            features.add(request.response_format.type)
        if len(features) > 1 and "+".join(sorted(features)) not in surface.combinations:
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
    description: str | None = None

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
class ReasoningItem:
    """Returned private text/summary and optional opaque stateless continuation."""

    id: str | None = None
    summary: tuple[str, ...] = ()
    text: tuple[str, ...] = ()
    encrypted_content: str | None = None
    tool_call_index: int = 0

    def __post_init__(self) -> None:
        if type(self.tool_call_index) is not int or self.tool_call_index < 0:
            raise ValueError("Reasoning position must be a nonnegative Tool-call index")
        object.__setattr__(self, "summary", tuple(self.summary))
        object.__setattr__(self, "text", tuple(self.text))


@dataclass(frozen=True)
class ReasoningContinuation:
    """Private Provider data paired with its exact accepted Message."""

    message: Message
    items: tuple[ReasoningItem, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        if any(
            item.tool_call_index > len(self.message.tool_calls) for item in self.items
        ):
            raise ValueError(
                "Reasoning position is outside the accepted Tool-call Message"
            )


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
    structured_output: StructuredOutput | None = None
    structured_plan: StructuredOutputPlan | None = field(default=None, init=False)
    reasoning: ReasoningControls | None = None
    continuations: tuple[ReasoningContinuation, ...] = ()
    vllm_options: VllmOptions | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "continuations", tuple(self.continuations))
        if any(
            item.message not in self.messages or not item.message.tool_calls
            for item in self.continuations
        ):
            raise ValueError(
                "Reasoning continuation requires its accepted Tool-call Message"
            )
        output = self.structured_output
        if output is not None:
            if self.response_format.type != "text":
                raise ValueError(
                    "Choose structured_output or response_format, not both"
                )
            plan = compile_structured_output(output)
            object.__setattr__(self, "structured_plan", plan)
            object.__setattr__(
                self,
                "response_format",
                ResponseFormat(
                    "json_schema",
                    plan.name,
                    plan.schema,
                    plan.strict,
                    plan.description,
                ),
            )
        elif self.response_format.type == "json_schema":
            schema = self.response_format.schema
            if not isinstance(schema, Mapping):
                raise ProviderError("unsupported_schema")
            object.__setattr__(
                self,
                "structured_plan",
                compile_structured_output(
                    JsonSchemaSpec(
                        self.response_format.name,
                        schema,
                        self.response_format.strict,
                        self.response_format.description,
                    )
                ),
            )
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "tools", tuple(self.tools))
        if any(not isinstance(tool, ToolPlan) for tool in self.tools):
            raise ProviderError("unsupported_feature")
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
    parsed: BaseModel | FrozenJsonValue = None
    reasoning: tuple[ReasoningItem, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", immutable_data(self.metadata))
        object.__setattr__(self, "reasoning", tuple(self.reasoning))
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


class _HTTPProvider:
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

    api: str
    endpoint: str

    @property
    def capabilities(self) -> ProviderCapabilities:
        if self._plan.endpoint_profile is not None:
            return CompatibleCapabilities(self._plan)
        if self._plan.type == "openai-compatible" and self.api == "responses":
            return ProviderCapabilities({})
        return ProviderCapabilities(
            {
                self.api: SurfaceCapabilities(
                    pydantic_round_trip=True,
                    reasoning=self.api == "responses",
                    reasoning_controls=frozenset(
                        {"effort", "summary"} if self.api == "responses" else {"effort"}
                    ),
                )
            }
        )

    def _body(self, request: ProviderRequest) -> dict[str, JsonValue]:
        raise NotImplementedError

    def _normalize(
        self,
        raw: JsonValue,
        request_id: str | None,
        latency: float,
    ) -> ProviderResponse:
        raise NotImplementedError

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        import httpx

        self.capabilities.require(self._plan.api, request)
        if self._closed:
            raise ProviderError("invalid_request")
        started = monotonic()
        try:
            body = self._body(request)
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
            response = await self._client.post(self.endpoint, json=body)
            request_id = self._scrub(response.headers.get("x-request-id"))
            if not response.is_success:
                raise _http_error(response, request_id)
            result: ProviderResponse | None = None
            try:
                raw = self._scrub_data(parse_json(response.text, "provider response"))
                result = self._normalize(raw, request_id, monotonic() - started)
                declared = self.capabilities.surfaces[self._plan.api]
                if (
                    (result.message.tool_calls and not declared.function_tools)
                    or (
                        len(result.message.tool_calls) > 1
                        and not declared.parallel_tool_calls
                    )
                    or (result.reasoning and not declared.reasoning)
                ):
                    raise ProviderError("unsupported_feature", request_id=request_id)
                if request.structured_plan is not None:
                    if result.refused:
                        raise ProviderError("refusal", request_id=request_id)
                    if result.finish_state in {"length", "content_filter"}:
                        raise ProviderError("incomplete", request_id=request_id)
                    if result.message.tool_calls:
                        raise StructuredOutputValidationError(
                            "schema_mismatch", request_id=request_id
                        )
                    try:
                        decoded = parse_json(
                            result.message.content, "structured output"
                        )
                    except (ValueError, RecursionError):
                        raise StructuredOutputValidationError(
                            "invalid_json", request_id=request_id
                        ) from None
                    scrubbed = self._scrub_data(decoded)
                    if scrubbed != decoded:
                        result = replace(
                            result,
                            message=replace(
                                result.message, content=canonical_json(scrubbed)
                            ),
                        )
                    value = validate_structured_output(
                        result.message.content,
                        request.structured_plan,
                        request.structured_output
                        if isinstance(request.structured_output, type)
                        else None,
                    )
                    result = replace(result, parsed=value)
                return result
            except ProviderError as exc:
                if result is not None:
                    # Even invalid structured content has a completed model-call
                    # identity, usage and private reasoning. Never store its draft.
                    exc.metadata = immutable_data(
                        {
                            **exc.metadata,
                            "response": response_evidence(
                                result, request, retain=self._plan.retain_reasoning
                            ),
                        }
                    )
                raise
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


class ChatCompletionsProvider(_HTTPProvider):
    """Stateless Chat Completions adapter with local structured validation."""

    api = "chat_completions"
    endpoint = "chat/completions"

    def _body(self, request: ProviderRequest) -> dict[str, JsonValue]:
        return _request_body(request)

    def _normalize(
        self,
        raw: JsonValue,
        request_id: str | None,
        latency: float,
    ) -> ProviderResponse:
        return _response(
            _Completion.model_validate(raw),
            self._plan.id,
            request_id,
            latency,
            self._scrub_data,
        )


class ResponsesProvider(_HTTPProvider):
    """Stateless Responses adapter; only framework-reviewed function Tools."""

    api = "responses"
    endpoint = "responses"

    def _body(self, request: ProviderRequest) -> dict[str, JsonValue]:
        from agentinstruct.responses import request_body

        return request_body(request)

    def _normalize(
        self,
        raw: JsonValue,
        request_id: str | None,
        latency: float,
    ) -> ProviderResponse:
        from agentinstruct.responses import normalize_response

        return normalize_response(
            raw, self._plan.id, request_id, latency, self._scrub_data
        )


def create_provider(plan: ProviderPlan) -> Provider:
    if plan.type == "vllm":
        from agentinstruct.vllm import VllmProvider

        return VllmProvider(plan)
    if plan.type == "openai-compatible" and plan.api == "responses":
        surface = (
            plan.endpoint_profile.surfaces.get("responses")
            if plan.endpoint_profile
            else None
        )
        if surface is None or surface.conformance != "passed":
            raise ProviderError("unsupported_feature")
        return ResponsesProvider(plan)
    if plan.type == "openai" and plan.api == "responses":
        return ResponsesProvider(plan)
    if plan.type in {"openai", "openai-compatible"} and plan.api == "chat_completions":
        return ChatCompletionsProvider(plan)
    raise ProviderError("unsupported_feature")


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
            if request.response_format.description is not None:
                cast(dict[str, JsonValue], response_format["json_schema"])[
                    "description"
                ] = request.response_format.description
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
    if request.reasoning is not None and request.reasoning.effort is not None:
        body["reasoning_effort"] = request.reasoning.effort
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
    complete = choice.message.refusal is None and choice.finish_reason not in {
        "length",
        "content_filter",
    }
    for call in (choice.message.tool_calls or ()) if complete else ():
        arguments = redact(parse_json(call.function.arguments, "Tool arguments"))
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
    if complete and (choice.finish_reason == "tool_calls") != bool(calls):
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
        "stop" if choice.message.refusal is not None else choice.finish_reason,
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
        code = raw.get("error", {}).get("code")
    except (ValueError, AttributeError, TypeError):
        pass
    return classify_provider_error(
        code, status_code=response.status_code, request_id=request_id
    )


def reasoning_evidence(
    response: ProviderResponse, request: ProviderRequest, *, retain: bool
) -> Mapping[str, FrozenJsonValue]:
    """One retention rule shared by Agent, Reviewer and Verifier model-call Events."""
    return immutable_data(
        {
            "requested": request.reasoning,
            **({"vllm_options": request.vllm_options} if request.vllm_options else {}),
            "returned": bool(response.reasoning),
            "retained": bool(response.reasoning) and retain,
            "items": response.reasoning if retain else (),
        }
    )


def response_evidence(
    response: ProviderResponse, request: ProviderRequest, *, retain: bool
) -> Mapping[str, FrozenJsonValue]:
    """Safe call evidence shared by success and locally rejected structured results."""
    return immutable_data(
        {
            "model": response.model,
            "finish_state": response.finish_state,
            "usage": response.usage,
            "request_id": response.request_id,
            "latency_seconds": response.latency_seconds,
            "refused": response.refused,
            "metadata": response.metadata,
            "reasoning": reasoning_evidence(response, request, retain=retain),
        }
    )
