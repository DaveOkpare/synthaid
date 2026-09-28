"""Structured contracts at the schema compiler and public Provider boundaries."""

import json
from datetime import date
from enum import StrEnum
from typing import cast

import pytest
from pydantic import BaseModel, ConfigDict, Field

from agentinstruct.plans import JsonValue, ProviderPlan, canonical_json
from agentinstruct.providers import ChatCompletionsProvider, ProviderRequest
from agentinstruct.structured import JsonSchemaSpec, compile_structured_output
from agentinstruct.traces import Message
from tests.test_providers import FakeTransport, completion


class Label(StrEnum):
    good = "good"
    bad = "bad"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passed: bool
    label: Label
    note: str | None


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: list[Finding] = Field(alias="checks")
    day: date


def test_compiler_snapshots_schema_and_keeps_class_out_of_plan() -> None:
    plan = compile_structured_output(Report)
    assert plan.name == "Report"
    assert plan.qualified_type == f"{Report.__module__}:Report"
    assert plan.strict is True
    assert compile_structured_output(Report) == plan
    assert json.loads(canonical_json(plan))["schema"]["required"] == ["checks", "day"]
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    explicit = compile_structured_output(JsonSchemaSpec("decision", schema))
    schema["properties"] = {}
    assert explicit.schema["properties"] == {"ok": {"type": "boolean"}}
    assert explicit.qualified_type is None
    with pytest.raises(TypeError):
        cast(dict[str, object], explicit.schema)["title"] = "changed"


@pytest.mark.asyncio
async def test_provider_round_trips_nested_alias_enum_null_and_date() -> None:
    transport = FakeTransport(
        completion(
            '{"checks":[{"passed":true,"label":"good","note":null}],"day":"2026-09-28"}'
        )
    )
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        result = await provider.generate(
            ProviderRequest(
                "model",
                (Message("user", "Evaluate"),),
                structured_output=Report,
            )
        )
    finally:
        await provider.aclose()
    assert isinstance(result.parsed, Report)
    assert result.parsed.findings[0] == Finding(
        passed=True, label=Label.good, note=None
    )
    assert result.parsed.day == date(2026, 9, 28)
    body = json.loads(transport.requests[0].content)
    assert (
        body["response_format"]["json_schema"]["schema"]["$defs"]["Finding"][
            "additionalProperties"
        ]
        is False
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "kind"),
    [
        (
            '{"checks":[{"passed":"true","label":"good","note":null}],"day":"2026-09-28"}',
            "schema_mismatch",
        ),
        (
            '{"checks":[{"passed":1,"label":"good","note":null}],"day":"2026-09-28"}',
            "schema_mismatch",
        ),
        (
            '{"checks":[{"passed":true,"label":"unknown","note":null}],"day":"2026-09-28"}',
            "schema_mismatch",
        ),
        ('{"checks":[],"day":"2026-09-28","extra":true}', "schema_mismatch"),
        ('{"checks":[],"day":null}', "schema_mismatch"),
        (
            '{"checks":[{"passed":true,"passed":false,"label":"good","note":null}],"day":"2026-09-28"}',
            "invalid_json",
        ),
        ('{"checks":[],"day":NaN}', "invalid_json"),
        ('{"checks":[],"day":1e999}', "invalid_json"),
        ('{"checks":', "invalid_json"),
    ],
)
async def test_strict_server_claim_never_bypasses_local_validation(
    content: str, kind: str
) -> None:
    from agentinstruct.provider_errors import StructuredOutputValidationError

    transport = FakeTransport(completion(content))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        with pytest.raises(StructuredOutputValidationError) as error:
            await provider.generate(
                ProviderRequest(
                    "model", (Message("user", "Evaluate"),), structured_output=Report
                )
            )
        assert error.value.kind == kind
    finally:
        await provider.aclose()
    assert len(transport.requests) == 1 and transport.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "kind"),
    [
        ("refusal", "refusal"),
        ("length", "incomplete"),
        ("content_filter", "incomplete"),
    ],
)
async def test_refusal_and_incomplete_are_distinct_from_json_failure(
    state: str, kind: str
) -> None:
    import httpx

    from agentinstruct.providers import ProviderError

    raw = completion("not json").json()
    if state == "refusal":
        raw["choices"][0]["message"]["refusal"] = "Cannot judge"
    else:
        raw["choices"][0]["finish_reason"] = state
    transport = FakeTransport(httpx.Response(200, json=raw))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(
                ProviderRequest(
                    "model", (Message("user", "Evaluate"),), structured_output=Report
                )
            )
        assert error.value.kind == kind
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_explicit_json_schema_result_is_validated_and_detached() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"values": {"type": "array", "items": {"type": "boolean"}}},
        "required": ["values"],
        "additionalProperties": False,
    }
    output = JsonSchemaSpec("values", schema, description="Checked values")
    request = ProviderRequest(
        "model", (Message("user", "Evaluate"),), structured_output=output
    )
    schema["required"] = []
    transport = FakeTransport(completion('{"values":[true,false]}'))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        response = await provider.generate(request)
    finally:
        await provider.aclose()
    assert response.parsed == {"values": (True, False)}
    wire = json.loads(transport.requests[0].content)["response_format"]["json_schema"]
    assert wire["schema"]["required"] == ["values"]
    assert wire["description"] == "Checked values"


class RecursiveNode(BaseModel):
    name: str
    children: list["RecursiveNode"]


@pytest.mark.asyncio
async def test_recursive_local_references_are_supported() -> None:
    transport = FakeTransport(
        completion('{"name":"root","children":[{"name":"child","children":[]}]}')
    )
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        result = await provider.generate(
            ProviderRequest(
                "model", (Message("user", "Evaluate"),), structured_output=RecursiveNode
            )
        )
    finally:
        await provider.aclose()
    assert isinstance(result.parsed, RecursiveNode)
    assert result.parsed.children[0].name == "child"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "keyword",
    [
        "allOf",
        "not",
        "if",
        "then",
        "else",
        "dependentRequired",
        "dependentSchemas",
        "patternProperties",
        "oneOf",
    ],
)
async def test_unsupported_schema_fails_before_transport(keyword: str) -> None:
    from agentinstruct.provider_errors import StructuredOutputValidationError

    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    schema[keyword] = [] if keyword in {"allOf", "oneOf"} else {}
    transport = FakeTransport()
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        with pytest.raises(StructuredOutputValidationError) as error:
            await provider.generate(
                ProviderRequest(
                    "model",
                    (Message("user", "Evaluate"),),
                    structured_output=JsonSchemaSpec("bad", schema),
                )
            )
        assert error.value.kind == "unsupported_schema"
    finally:
        await provider.aclose()
    assert not transport.requests


@pytest.mark.asyncio
async def test_explicit_schema_format_is_enforced_locally() -> None:
    from agentinstruct.provider_errors import StructuredOutputValidationError

    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"day": {"type": "string", "format": "date"}},
        "required": ["day"],
        "additionalProperties": False,
    }
    transport = FakeTransport(completion('{"day":"not-a-date"}'))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        with pytest.raises(StructuredOutputValidationError) as error:
            await provider.generate(
                ProviderRequest(
                    "model",
                    (Message("user", "Evaluate"),),
                    structured_output=JsonSchemaSpec("date", schema),
                )
            )
        assert error.value.kind == "schema_mismatch"
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_json_escaped_credentials_are_scrubbed_before_typed_result_and_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SecretEcho(BaseModel):
        feedback: str

    secret = 'credential-with-"quote'
    monkeypatch.setenv("STRUCTURED_KEY", secret)
    transport = FakeTransport(completion(json.dumps({"feedback": secret})))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            "STRUCTURED_KEY",
        ),
        transport=transport,
    )
    try:
        result = await provider.generate(
            ProviderRequest(
                "model", (Message("user", "Evaluate"),), structured_output=SecretEcho
            )
        )
    finally:
        await provider.aclose()
    assert isinstance(result.parsed, SecretEcho)
    assert result.parsed.feedback == "[REDACTED]"
    assert json.loads(result.message.content) == {"feedback": "[REDACTED]"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "missing_required",
        "permissive_object",
        "remote_ref",
        "missing_ref",
        "boolean_variant",
        "unsupported_format",
    ],
)
async def test_known_schema_incompatibilities_fail_without_inference(case: str) -> None:
    from agentinstruct import StructuredOutputValidationError

    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    if case == "missing_required":
        schema["required"] = []
    elif case == "permissive_object":
        schema["additionalProperties"] = True
    else:
        variants: dict[str, JsonValue] = {
            "remote_ref": {"$ref": "https://unreachable.example/schema.json"},
            "missing_ref": {"$ref": "#/$defs/absent"},
            "boolean_variant": {"anyOf": [True, {"type": "string"}]},
            "unsupported_format": {"type": "string", "format": "password"},
        }
        schema["properties"] = {"value": variants[case]}
    transport = FakeTransport()
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        with pytest.raises(StructuredOutputValidationError) as error:
            await provider.generate(
                ProviderRequest(
                    "model",
                    (Message("user", "Evaluate"),),
                    structured_output=JsonSchemaSpec("bad", schema),
                )
            )
        assert error.value.kind == "unsupported_schema"
    finally:
        await provider.aclose()
    assert not transport.requests


@pytest.mark.asyncio
async def test_current_schema_limits_allow_101_properties_and_six_levels() -> None:
    properties: dict[str, JsonValue] = {
        f"item{index}": {"type": "boolean"} for index in range(101)
    }
    schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    value: dict[str, JsonValue] = {key: True for key in properties}
    for _ in range(5):
        schema = {
            "type": "object",
            "properties": {"nested": schema},
            "required": ["nested"],
            "additionalProperties": False,
        }
        value = {"nested": value}
    transport = FakeTransport(completion(json.dumps(value)))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        response = await provider.generate(
            ProviderRequest(
                "model",
                (Message("user", "Evaluate"),),
                structured_output=JsonSchemaSpec("many", schema),
            )
        )
    finally:
        await provider.aclose()
    assert canonical_json(response.parsed) == canonical_json(value)


def test_fingerprints_ignore_mapping_order_but_track_contract_changes() -> None:
    first: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    reordered = dict(reversed(list(first.items())))
    plan = compile_structured_output(JsonSchemaSpec("decision", first))
    assert (
        compile_structured_output(JsonSchemaSpec("decision", reordered)).fingerprint
        == plan.fingerprint
    )
    first["properties"] = {"ok": {"type": "string"}}
    assert (
        compile_structured_output(JsonSchemaSpec("decision", first)).fingerprint
        != plan.fingerprint
    )
    assert (
        compile_structured_output(
            JsonSchemaSpec("decision", reordered, strict=False)
        ).fingerprint
        != plan.fingerprint
    )


def test_pydantic_schema_generation_failure_is_typed_before_inference() -> None:
    from collections.abc import Callable

    from agentinstruct import StructuredOutputValidationError

    class UnsupportedResult(BaseModel):
        callback: Callable[[], bool]

    with pytest.raises(StructuredOutputValidationError) as error:
        compile_structured_output(UnsupportedResult)
    assert error.value.kind == "unsupported_schema"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["refusal", "length"])
async def test_structured_failure_state_precedes_tool_argument_parsing(
    state: str,
) -> None:
    import httpx

    from agentinstruct import ProviderError
    from tests.test_providers import wire_call

    raw = wire_call().json()
    raw["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = "not json"
    if state == "refusal":
        raw["choices"][0]["message"]["refusal"] = "Cannot judge"
    else:
        raw["choices"][0]["finish_reason"] = state
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=FakeTransport(httpx.Response(200, json=raw)),
    )
    try:
        with pytest.raises(ProviderError) as error:
            await provider.generate(
                ProviderRequest(
                    "model", (Message("user", "Evaluate"),), structured_output=Report
                )
            )
        assert error.value.kind == ("incomplete" if state == "length" else "refusal")
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    [
        "contains",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
        "additionalItems",
        "dependencies",
        "contentSchema",
        "tuple_items",
        "extends",
        "disallow",
        "schema_type",
    ],
)
@pytest.mark.parametrize("problem", ["remote_reference", "unavailable_format"])
async def test_non_strict_nested_contract_errors_fail_before_inference(
    location: str,
    problem: str,
) -> None:
    from agentinstruct import StructuredOutputValidationError

    child: dict[str, JsonValue] = (
        {"$ref": "https://unreachable.example/schema.json"}
        if problem == "remote_reference"
        else {"type": "string", "format": "unsupported-test-format"}
    )
    schema: dict[str, JsonValue] = {}
    if location == "dependencies":
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "dependencies": {"value": child},
        }
    elif location in {"tuple_items", "additionalItems"}:
        schema = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "array",
            "items": [child] if location == "tuple_items" else [{}],
        }
        if location == "additionalItems":
            schema["additionalItems"] = child
    elif location in {"extends", "disallow", "schema_type"}:
        schema = {
            "$schema": "http://json-schema.org/draft-03/schema#",
            "type" if location == "schema_type" else location: [child],
        }
    else:
        schema[location] = child
    transport = FakeTransport(completion("{}"))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        with pytest.raises(StructuredOutputValidationError) as error:
            await provider.generate(
                ProviderRequest(
                    "model",
                    (Message("user", "Evaluate"),),
                    structured_output=JsonSchemaSpec("nested", schema, strict=False),
                )
            )
        assert error.value.kind == "unsupported_schema"
    finally:
        await provider.aclose()
    assert not transport.requests and transport.closed


@pytest.mark.asyncio
async def test_schema_traversal_keeps_annotations_and_property_names_as_data() -> None:
    value: dict[str, JsonValue] = {
        "$ref": "https://data.example/schema.json",
        "format": "an-instance-value",
        "contains": "an-instance-property",
    }
    schema: dict[str, JsonValue] = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {
            "$ref": {"type": "string"},
            "format": {"type": "string"},
            "contains": {"type": "string"},
        },
        "dependencies": {"$ref": ["format"]},
        "default": value,
        "examples": [value],
        "enum": [value],
        "const": value,
    }
    transport = FakeTransport(completion(json.dumps(value)))
    provider = ChatCompletionsProvider(
        ProviderPlan(
            "test",
            "openai-compatible",
            "chat_completions",
            "https://test.example/v1",
            None,
        ),
        transport=transport,
    )
    try:
        result = await provider.generate(
            ProviderRequest(
                "model",
                (Message("user", "Evaluate"),),
                structured_output=JsonSchemaSpec("data", schema, strict=False),
            )
        )
    finally:
        await provider.aclose()
    assert result.parsed == value
    assert len(transport.requests) == 1 and transport.closed
