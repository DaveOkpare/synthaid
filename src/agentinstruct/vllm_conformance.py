"""Explicit opt-in, report-producing checks against an external pinned vLLM server.

Importing or collecting tests never runs this module. The CLI requires --allow-live,
explicit endpoint and hardware, probes the version/model, and writes a new report.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel

from agentinstruct.plans import (
    FrozenJsonValue,
    JsonValue,
    ProviderPlan,
    ToolPlan,
    VllmChatTemplateKwargs,
    VllmMode,
    VllmOptions,
    VllmStructuredOutputs,
    canonical_json,
    content_digest,
    json_value,
)
from agentinstruct.providers import (
    ChatCompletionsProvider,
    InferenceControls,
    NamedToolChoice,
    Provider,
    ProviderCapabilities,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ReasoningContinuation,
    ResponseFormat,
)
from agentinstruct.seeds import parse_json
from agentinstruct.store import timestamp
from agentinstruct.task_config import ProviderConfig
from agentinstruct.tools import schema_validator
from agentinstruct.traces import Message
from agentinstruct.vllm import VllmCapabilities, VllmProvider


class _Answer(BaseModel):
    answer: int


_ANSWER_SCHEMA: dict[str, FrozenJsonValue] = {
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ("answer",),
    "additionalProperties": False,
}
_LOOKUP = ToolPlan(
    "lookup",
    "Return a secret marker for this label.",
    {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": ("Ada", "Bob")}},
        "required": ("label",),
        "additionalProperties": False,
    },
)


@dataclass(frozen=True)
class ConformanceCase:
    id: str
    request: ProviderRequest
    expected: Literal["text", "json", "yes", "tag", "tools", "no_tools"]
    reasoning: bool = False
    multiple_calls: bool = False
    no_reasoning: bool = False


def _native(mode: VllmMode) -> VllmStructuredOutputs:
    match mode:
        case "json":
            return VllmStructuredOutputs(json=_ANSWER_SCHEMA)
        case "json_object":
            return VllmStructuredOutputs(json_object=True)
        case "choice":
            return VllmStructuredOutputs(choice=("yes",))
        case "regex":
            return VllmStructuredOutputs(regex="yes")
        case "grammar":
            return VllmStructuredOutputs(grammar='root ::= "yes"')
        case "structural_tag":
            return VllmStructuredOutputs(
                structural_tag=canonical_json(
                    {
                        "type": "structural_tag",
                        "structures": [
                            {
                                "begin": "<answer>",
                                "schema": _ANSWER_SCHEMA,
                                "end": "</answer>",
                            }
                        ],
                        "triggers": ["<answer>"],
                    }
                )
            )


def conformance_cases(plan: ProviderPlan) -> tuple[ConformanceCase, ...]:
    """Derive fixtures for every declared mode, control, modifier and combination."""
    if plan.vllm_profile is None or plan.api not in plan.vllm_profile.surfaces:
        raise ValueError("Conformance needs an explicit selected surface")
    profile = plan.vllm_profile
    surface = profile.surfaces[plan.api]
    cases: list[ConformanceCase] = []

    def case(
        identifier: str,
        features: set[str],
        *,
        choice: Literal["none", "auto", "required", "named"] | None = None,
        multiple: bool = False,
    ) -> ConformanceCase:
        options = replace(plan.vllm_options or VllmOptions(), structured_outputs=None)
        if "enable_thinking" in surface.reasoning_controls:
            options = replace(
                options,
                chat_template_kwargs=VllmChatTemplateKwargs(
                    enable_thinking="reasoning" in features
                ),
            )
        require_reasoning = "reasoning" in features or (
            surface.reasoning and "enable_thinking" not in surface.reasoning_controls
        )
        if require_reasoning and "include_reasoning" in surface.reasoning_controls:
            # A suppression default cannot serve as evidence of reasoning support.
            # The dedicated control case below still tests explicit suppression.
            options = replace(options, include_reasoning=True)
        prompt = "Reply with exactly the word yes."
        expected: Literal["text", "json", "yes", "tag", "tools", "no_tools"] = "text"
        response_format = ResponseFormat()
        structured_output = None
        native = next(
            (
                part.removeprefix("native:")
                for part in features
                if part.startswith("native:")
            ),
            None,
        )
        if native:
            options = replace(
                options, structured_outputs=_native(cast(VllmMode, native))
            )
            if native in {"json", "json_object"}:
                expected = "json"
            elif native == "structural_tag":
                expected = "tag"
            else:
                expected = "yes"
        elif "json_schema" in features:
            structured_output = _Answer
            expected = "json"
        elif "json_object" in features:
            response_format = ResponseFormat("json_object")
            expected = "json"
        if expected in {"json", "tag"}:
            prompt = 'What is 3 + 4? Reply as JSON: {"answer": 7}.'
            if expected == "tag":
                prompt += " Wrap the JSON in <answer> and </answer>."
        if "tools" in features or choice is not None:
            prompt = (
                "Call lookup for Ada. "
                "Use the returned secret marker in your final answer."
            )
            if multiple:
                prompt = (
                    "Call lookup for Ada and Bob together. "
                    "Use both returned markers in your final answer."
                )
            if choice == "none":
                prompt = "Reply yes without calling any Tool."
            expected = "no_tools" if choice == "none" else "tools"
        return ConformanceCase(
            identifier,
            ProviderRequest(
                profile.model,
                (Message("user", prompt),),
                tools=(_LOOKUP,) if expected in {"tools", "no_tools"} else (),
                tool_choice=NamedToolChoice("lookup")
                if choice == "named"
                else (choice or "auto")
                if expected == "tools"
                else choice,
                parallel_tool_calls=True if multiple else None,
                response_format=response_format,
                structured_output=structured_output,
                inference=InferenceControls(temperature=0.0, max_tokens=2048),
                vllm_options=options,
            ),
            expected,
            require_reasoning,
            multiple,
        )

    cases.append(case("text", set()))
    for mode in surface.response_formats:
        if mode != "text":
            cases.append(case(mode, {mode}))
    for native_mode in surface.native_modes:
        cases.append(case("native:" + native_mode, {"native:" + native_mode}))
    if surface.reasoning:
        cases.append(case("reasoning", {"reasoning"}))
    for tool_mode in surface.tool_choices:
        cases.append(case("tools:" + tool_mode, {"tools"}, choice=tool_mode))
    if surface.parallel_tool_calls:
        cases.append(case("tools:parallel", {"tools"}, choice="auto", multiple=True))
    for combination in surface.combinations:
        cases.append(case(combination, set(combination.split("+"))))
    for control in surface.reasoning_controls:
        sample = case("control:" + control, {"reasoning"})
        options = sample.request.vllm_options or VllmOptions()
        if control == "effort":
            options = replace(options, reasoning_effort="low")
        elif control == "thinking_token_budget":
            options = replace(options, thinking_token_budget=128)
        elif control == "include_reasoning":
            options = replace(options, include_reasoning=False)
            sample = replace(sample, reasoning=False, no_reasoning=True)
        elif control == "enable_thinking":
            options = replace(
                options,
                chat_template_kwargs=VllmChatTemplateKwargs(enable_thinking=False),
            )
            sample = replace(sample, reasoning=False)
        cases.append(
            replace(sample, request=replace(sample.request, vllm_options=options))
        )
    for modifier in surface.structured_modifiers:
        if not surface.native_modes:
            raise ValueError("Structured modifiers require a declared native mode")
        sample = case("modifier:" + modifier, {"native:" + surface.native_modes[0]})
        options = sample.request.vllm_options or VllmOptions()
        assert options.structured_outputs is not None
        native_options = options.structured_outputs
        if modifier == "whitespace_pattern":
            native_options = replace(native_options, whitespace_pattern=r"[\n\t ]*")
        elif modifier == "disable_any_whitespace":
            native_options = replace(native_options, disable_any_whitespace=True)
        else:
            native_options = replace(native_options, disable_additional_properties=True)
        cases.append(
            replace(
                sample,
                request=replace(
                    sample.request,
                    vllm_options=replace(options, structured_outputs=native_options),
                ),
            )
        )
    return tuple(cases)


def _check(case: ConformanceCase, response: ProviderResponse) -> bool:
    if response.refused or response.finish_state not in {"stop", "tool_calls"}:
        return False
    if case.reasoning and not response.reasoning:
        return False
    if case.no_reasoning and response.reasoning:
        return False
    content = response.message.content.strip()
    if case.expected == "tools":
        calls = response.message.tool_calls
        if not calls or (case.multiple_calls and len(calls) < 2):
            return False
        for call in calls:
            if call.function.name != "lookup" or not schema_validator(
                _LOOKUP.input_schema
            ).is_valid(json_value(call.function.arguments)):
                return False
        return {call.function.arguments["label"] for call in calls} == (
            {"Ada", "Bob"} if case.multiple_calls else {"Ada"}
        )
    if response.message.tool_calls:
        return False
    if case.expected == "yes":
        return content == "yes"
    if case.expected == "tag":
        matched = re.fullmatch(r"<answer>(.*?)</answer>", content, re.DOTALL)
        if not matched:
            return False
        content = matched.group(1)
    if case.expected in {"json", "tag"}:
        try:
            return parse_json(content, "conformance answer") == {"answer": 7}
        except ValueError:
            return False
    return bool(content)


class _Probe(VllmProvider):
    """Harness-only transport for testing a previously unverified Responses surface."""

    def __init__(self, plan: ProviderPlan) -> None:
        ChatCompletionsProvider.__init__(self, plan)
        self.api = plan.api
        self.endpoint = "responses" if plan.api == "responses" else "chat/completions"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return VllmCapabilities(self._plan, conformance_probe=True)


async def run_conformance(
    plan: ProviderPlan,
    *,
    provider_factory: Callable[[ProviderPlan], Provider] | None = None,
) -> dict[str, JsonValue]:
    """Execute selected-surface cases; injected transports cannot claim a live pass."""
    cases = conformance_cases(plan)
    report: dict[str, JsonValue] = {
        "schema_version": "1",
        "suite": "agentinstruct-vllm-v1",
        "api": plan.api,
        "execution": "live" if provider_factory is None else "injected_transport",
        "started_at": timestamp(),
        "provider": json_value(plan),
        "cases": [],
    }
    results: list[JsonValue] = []
    provider = (provider_factory or _Probe)(plan)
    try:
        # Fail every known incompatibility before the first live model call.
        for case in cases:
            provider.capabilities.require(plan.api, case.request)
        for case in cases:
            result: dict[str, JsonValue] = {"id": case.id, "passed": False}
            try:
                response = await provider.generate(case.request)
                passed = _check(case, response)
                if passed and case.expected == "tools":
                    history = (*case.request.messages, response.message)
                    markers = []
                    for index, call in enumerate(response.message.tool_calls):
                        marker = "conformance-marker-7319-" + str(index)
                        markers.append(marker)
                        history += (Message("tool", marker, tool_call_id=call.id),)
                    continuation = ProviderRequest(
                        case.request.model,
                        history,
                        inference=case.request.inference,
                        vllm_options=replace(
                            case.request.vllm_options or VllmOptions(),
                            structured_outputs=None,
                        ),
                        continuations=(
                            ReasoningContinuation(response.message, response.reasoning),
                        )
                        if plan.api == "responses" and response.reasoning
                        else (),
                    )
                    final = await provider.generate(continuation)
                    passed = (
                        final.finish_state == "stop"
                        and not final.refused
                        and not final.message.tool_calls
                        and all(marker in final.message.content for marker in markers)
                    )
                result["passed"] = passed
                if not passed:
                    result["error"] = "semantic_mismatch"
            except ProviderError as exc:
                result["error"] = exc.kind
            results.append(result)
    finally:
        await provider.aclose()
    report["requests"] = {
        case.id: json_value(
            {
                "model": case.request.model,
                "messages": case.request.messages,
                "tools": case.request.tools,
                "tool_choice": case.request.tool_choice,
                "parallel_tool_calls": case.request.parallel_tool_calls,
                "response_format": case.request.response_format,
                "structured_output": case.request.structured_plan,
                "inference": case.request.inference,
                "vllm_options": case.request.vllm_options,
            }
        )
        for case in cases
    }
    report["cases"] = results
    report["finished_at"] = timestamp()
    report["passed"] = bool(results) and all(
        isinstance(item, dict) and item["passed"] for item in results
    )
    report["digest"] = content_digest(report)
    return report


async def _live(plan: ProviderPlan) -> dict[str, JsonValue]:
    import httpx

    assert plan.vllm_profile is not None and plan.base_url is not None
    secret = os.environ.get(plan.api_key_env) if plan.api_key_env else None
    if plan.api_key_env and not secret:
        raise ProviderError("authentication")
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {secret}"} if secret else {},
        timeout=30,
        follow_redirects=False,
        transport=httpx.AsyncHTTPTransport(retries=0),
    ) as client:
        version_response = await client.get(
            plan.base_url.rstrip("/").removesuffix("/v1") + "/version"
        )
        models_response = await client.get(plan.base_url.rstrip("/") + "/models")
        version_response.raise_for_status()
        models_response.raise_for_status()
        version = version_response.json()["version"]
        models = [item["id"] for item in models_response.json()["data"]]
        if (
            version != plan.vllm_profile.vllm_version
            or plan.vllm_profile.model not in models
        ):
            raise ProviderError("unsupported_feature")
    report = await run_conformance(plan)
    report["observed_server_version"] = version
    report["observed_model"] = plan.vllm_profile.model
    report.pop("digest")
    report["digest"] = content_digest(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--hardware", required=True)
    parser.add_argument(
        "--api", choices=("chat_completions", "responses"), default="chat_completions"
    )
    parser.add_argument("--api-key-env")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    # Validate all caller-supplied provenance and URL fields before any network.
    raw = parse_json(args.profile.read_text(), "vLLM profile")
    if not isinstance(raw, dict) or not isinstance(raw.get("vllm_profile"), dict):
        parser.error("Expected a vLLM Provider configuration")
    raw["base_url"] = args.base_url
    raw["api"] = args.api
    raw["api_key_env"] = args.api_key_env
    cast(dict[str, JsonValue], raw["vllm_profile"])["hardware"] = args.hardware
    try:
        config = ProviderConfig.model_validate(
            raw, context={"vllm_conformance_probe": True}
        )
    except ValueError:
        parser.error("Invalid conformance configuration")
    assert config.vllm_profile is not None
    plan = ProviderPlan(
        "conformance",
        "vllm",
        config.api or "chat_completions",
        config.base_url,
        config.api_key_env,
        config.retain_reasoning,
        config.vllm_profile,
        config.vllm_options,
    )
    # Exclusive create before inference avoids spending a run on an unusable path.
    with args.output.open("x", encoding="utf-8") as output:
        try:
            report = asyncio.run(_live(plan))
        except Exception as exc:
            report = {
                "passed": False,
                "execution": "live",
                "provider": json_value(plan),
                "error": exc.kind
                if isinstance(exc, ProviderError)
                else "conformance_setup_failure",
            }
        output.write(canonical_json(report) + "\n")
    print(
        "Conformance passed."
        if report["passed"]
        else "Conformance failed; inspect the report."
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
