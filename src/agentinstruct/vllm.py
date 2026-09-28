"""External vLLM adapter with explicit per-model, per-surface capabilities."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast

from agentinstruct.plans import (
    JsonSchema,
    JsonValue,
    ProviderPlan,
    VllmOptions,
    json_value,
)
from agentinstruct.providers import (
    ChatCompletionsProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ReasoningItem,
    SurfaceCapabilities,
)
from agentinstruct.tools import schema_validator

if TYPE_CHECKING:
    import httpx


def option_body(options: VllmOptions) -> dict[str, JsonValue]:
    """Omit unset typed fields while preserving nulls inside user JSON Schema."""
    raw = json_value(options)
    assert isinstance(raw, dict)
    body: dict[str, JsonValue] = {
        key: value for key, value in raw.items() if value is not None
    }
    for name in ("structured_outputs", "chat_template_kwargs"):
        nested = body.get(name)
        if isinstance(nested, dict):
            body[name] = {
                key: value for key, value in nested.items() if value is not None
            }
    return body


class VllmCapabilities(ProviderCapabilities):
    def __init__(self, plan: ProviderPlan, *, conformance_probe: bool = False) -> None:
        assert plan.vllm_profile is not None
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
                    native_extensions=frozenset({"vllm", *surface.native_modes}),
                )
                for api, surface in plan.vllm_profile.surfaces.items()
                if api == "chat_completions"
                or surface.conformance == "passed"
                or conformance_probe
            }
        )

    plan: ProviderPlan

    def require(self, api: str, request: ProviderRequest) -> None:
        super().require(api, request)
        profile = self.plan.vllm_profile
        assert profile is not None
        if request.model != profile.model:
            raise ProviderError("unsupported_feature")
        surface = profile.surfaces[api]
        options = request.vllm_options or self.plan.vllm_options or VllmOptions()
        controls = {
            "effort": options.reasoning_effort,
            "thinking_token_budget": options.thinking_token_budget,
            "include_reasoning": options.include_reasoning,
            "enable_thinking": options.chat_template_kwargs.enable_thinking
            if options.chat_template_kwargs
            else None,
        }
        if any(
            value is not None and name not in surface.reasoning_controls
            for name, value in controls.items()
        ):
            raise ProviderError("unsupported_feature")
        if (
            request.reasoning
            and request.reasoning.effort is not None
            and options.reasoning_effort is not None
            and request.reasoning.effort != options.reasoning_effort
        ):
            raise ProviderError("invalid_request")
        features: set[str] = set()
        if request.tools and request.tool_choice != "none":
            features.add("tools")
        if request.response_format.type != "text":
            features.add(request.response_format.type)
        if surface.reasoning and controls["enable_thinking"] is not False:
            # Extraction capability conservatively implies a reasoning model unless
            # its declared model-specific request explicitly disables thinking.
            features.add("reasoning")
        native = options.structured_outputs
        if native is not None:
            if native.mode not in surface.native_modes:
                raise ProviderError("unsupported_feature")
            if request.response_format.type != "text":
                raise ProviderError("invalid_request")
            for name in (
                "whitespace_pattern",
                "disable_any_whitespace",
                "disable_additional_properties",
            ):
                if (
                    getattr(native, name) is not None
                    and name not in surface.structured_modifiers
                ):
                    raise ProviderError("unsupported_feature")
            if native.json is not None:
                try:
                    schema_validator(cast(JsonSchema, native.json))
                except Exception:
                    raise ProviderError("invalid_request") from None
            features.add("native:" + native.mode)
        if len(features) > 1 and "+".join(sorted(features)) not in surface.combinations:
            raise ProviderError("unsupported_feature")
        if api == "chat_completions" and request.continuations:
            raise ProviderError("unsupported_feature")


class VllmProvider(ChatCompletionsProvider):
    """A configured external server; never imports an inference engine or retries."""

    def __init__(
        self,
        plan: ProviderPlan,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if plan.type != "vllm" or plan.vllm_profile is None or plan.base_url is None:
            raise ProviderError("unsupported_feature")
        surface = plan.vllm_profile.surfaces.get(plan.api)
        if surface is None or (
            plan.api == "responses" and surface.conformance != "passed"
        ):
            raise ProviderError("unsupported_feature")
        super().__init__(plan, transport=transport, timeout_seconds=timeout_seconds)
        self.api = plan.api
        self.endpoint = "responses" if plan.api == "responses" else "chat/completions"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return VllmCapabilities(self._plan)

    def _body(self, request: ProviderRequest) -> dict[str, JsonValue]:
        if self.api == "responses":
            from agentinstruct.responses import request_body

            body = request_body(request)
        else:
            body = super()._body(request)
        # Resolve defaults at the wire boundary without reconstructing the
        # request's already compiled structured-output contract.
        body.update(
            option_body(
                request.vllm_options or self._plan.vllm_options or VllmOptions()
            )
        )
        if self.api == "responses" and "reasoning_effort" in body:
            effort = body.pop("reasoning_effort")
            reasoning = body.get("reasoning", {})
            assert isinstance(reasoning, dict)
            body["reasoning"] = {**reasoning, "effort": effort}
        return body

    def _normalize(
        self, raw: JsonValue, request_id: str | None, latency: float
    ) -> ProviderResponse:
        if self.api == "responses":
            from agentinstruct.responses import normalize_response

            return normalize_response(
                raw, self._plan.id, request_id, latency, self._scrub_data
            )
        result = super()._normalize(raw, request_id, latency)
        assert isinstance(raw, dict)
        choices = raw["choices"]
        assert isinstance(choices, list) and isinstance(choices[0], dict)
        message = choices[0]["message"]
        assert isinstance(message, dict)
        reasoning = message.get("reasoning")
        if reasoning is not None and not isinstance(reasoning, str):
            raise ProviderError("malformed_response", request_id=request_id)
        if message.get("reasoning_content") is not None:
            # No older-server alias is currently claimed or tested by a profile.
            raise ProviderError("unsupported_feature", request_id=request_id)
        if (
            reasoning
            and not result.message.tool_calls
            and ("<tool_call>" in reasoning or '"tool_calls":' in reasoning)
            and not result.message.content.strip()
        ):
            raise ProviderError("malformed_response", request_id=request_id)
        surface = (
            self._plan.vllm_profile.surfaces[self.api]
            if self._plan.vllm_profile
            else None
        )
        if reasoning and surface is not None and not surface.reasoning:
            raise ProviderError("unsupported_feature", request_id=request_id)
        return replace(
            result, reasoning=(ReasoningItem(text=(reasoning,)),) if reasoning else ()
        )
