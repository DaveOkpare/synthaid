"""Portable immutable output schemas and mandatory local JSON validation."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from jsonschema import FormatChecker
from pydantic import BaseModel

from agentinstruct.plans import (
    FrozenJsonValue,
    JsonValue,
    StructuredOutputPlan,
    canonical_json,
    freeze,
    json_value,
)
from agentinstruct.provider_errors import StructuredOutputValidationError
from agentinstruct.seeds import parse_json
from agentinstruct.tools import schema_validator


@dataclass(frozen=True)
class JsonSchemaSpec:
    """Explicit authoring input; copied and frozen at compilation."""

    name: str
    schema: Mapping[str, JsonValue | FrozenJsonValue]
    strict: bool = True
    description: str | None = None


type StructuredOutput = type[BaseModel] | JsonSchemaSpec | StructuredOutputPlan


def _nodes(schema: dict[str, JsonValue]) -> list[dict[str, JsonValue]]:
    """Walk schemas, never arbitrary defaults, examples or property names."""
    result = [schema]
    for name in (
        "$defs",
        "definitions",
        "properties",
        "patternProperties",
        "dependentSchemas",
        "dependencies",
    ):
        children = schema.get(name)
        if isinstance(children, dict):
            for child in children.values():
                if isinstance(child, dict):
                    result.extend(_nodes(child))
    # Items and the draft-3 keywords can hold one schema or an ordered list.
    # Only dictionaries in these known schema positions are traversed; strings
    # in type/disallow and property dependency lists are ordinary declarations.
    for name in (
        "items",
        "additionalItems",
        "additionalProperties",
        "contains",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contentSchema",
        "not",
        "if",
        "then",
        "else",
        "anyOf",
        "allOf",
        "oneOf",
        "prefixItems",
        "extends",
        "disallow",
        "type",
    ):
        child = schema.get(name)
        if isinstance(child, dict):
            result.extend(_nodes(child))
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    result.extend(_nodes(item))
    return result


def compile_structured_output(output: StructuredOutput) -> StructuredOutputPlan:
    """Compile without network, imports of model clients, or live class persistence."""
    if isinstance(output, StructuredOutputPlan):
        return output
    qualified_type = None
    if isinstance(output, type) and issubclass(output, BaseModel):
        try:
            data = cast(
                dict[str, JsonValue],
                output.model_json_schema(by_alias=True, mode="validation"),
            )
        except Exception:
            raise StructuredOutputValidationError("unsupported_schema") from None
        name = output.__name__
        description = data.get("description")
        description = description if isinstance(description, str) else None
        strict = True
        qualified_type = f"{output.__module__}:{output.__qualname__}"
        # Pydantic defaults become required wire values. Explicit permissive maps
        # remain unchanged and are rejected by strict-surface preflight.
        for node in _nodes(data):
            if node.get("type") == "object":
                node.setdefault("additionalProperties", False)
                properties = node.get("properties", {})
                if isinstance(properties, dict):
                    node["required"] = list(properties)
            node.pop("default", None)
    elif isinstance(output, JsonSchemaSpec):
        data = cast(dict[str, JsonValue], json_value(output.schema))
        name, description, strict = output.name, output.description, output.strict
    else:
        raise TypeError(
            "Structured output requires a BaseModel class or JsonSchemaSpec"
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or type(strict) is not bool:
        raise StructuredOutputValidationError("unsupported_schema")
    try:
        schema_validator(cast(Mapping[str, FrozenJsonValue], freeze(data)))
        canonical_json(data)
        for node in _nodes(data):
            if "$ref" in node:
                _resolve(data, node["$ref"])
            if any(key in node for key in ("$id", "$dynamicRef", "$recursiveRef")):
                raise ValueError("Only local JSON Pointer references are supported")
    except Exception:
        raise StructuredOutputValidationError("unsupported_schema") from None
    return StructuredOutputPlan(
        name,
        cast(Mapping[str, FrozenJsonValue], freeze(data)),
        strict,
        description,
        qualified_type,
    )


def _resolve(root: dict[str, JsonValue], reference: JsonValue) -> dict[str, JsonValue]:
    if not isinstance(reference, str) or (
        reference != "#" and not reference.startswith("#/")
    ):
        raise ValueError("Only local references are supported")
    value: JsonValue = root
    for part in reference[2:].split("/") if reference != "#" else ():
        if not isinstance(value, dict):
            raise ValueError("Invalid schema reference")
        value = value[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(value, dict):
        raise ValueError("Invalid schema reference")
    return value


def preflight_structured_output(plan: StructuredOutputPlan) -> None:
    """Check the documented OpenAI strict JSON Schema subset before inference.

    Recursive local references are supported. Finite schema paths count toward
    the ten-level nesting limit; recursive edges do not expand indefinitely.
    """
    data = cast(dict[str, JsonValue], json_value(plan.schema))
    try:
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", plan.name)
            or type(plan.strict) is not bool
        ):
            raise ValueError("Invalid schema metadata")
        schema_validator(plan.schema)
        nodes = _nodes(data)
        # Offline reference checks also apply when server strictness is disabled.
        for node in nodes:
            if "$ref" in node:
                _resolve(data, node["$ref"])
            if any(key in node for key in ("$id", "$dynamicRef", "$recursiveRef")):
                raise ValueError("Only local JSON Pointer references are supported")
            if "pattern" in node:
                pattern = node["pattern"]
                if not isinstance(pattern, str):
                    raise ValueError("Invalid pattern")
                re.compile(pattern)
            if "format" in node and node["format"] not in FormatChecker().checkers:
                raise ValueError("Format validation is unavailable locally")
        if not plan.strict:
            return
        root = _resolve(data, data["$ref"]) if "$ref" in data else data
        if root.get("type") != "object" or "anyOf" in root:
            raise ValueError("Root must be an object")
        allowed = {
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
        properties_count = enum_count = string_length = 0
        for node in nodes:
            if set(node) - allowed:
                raise ValueError("Unsupported schema keyword")
            if not any(key in node for key in ("type", "anyOf", "$ref")):
                raise ValueError("A strict schema must declare a supported type")
            if "format" in node and node["format"] not in {
                "date-time",
                "time",
                "date",
                "duration",
                "email",
                "hostname",
                "ipv4",
                "ipv6",
                "uuid",
            }:
                raise ValueError("Unsupported string format")
            properties = node.get("properties", {})
            types = node.get("type")
            types = types if isinstance(types, list) else [types]
            if "array" in types and not isinstance(node.get("items"), dict):
                raise ValueError("Arrays require a supported item schema")
            variants = node.get("anyOf")
            if isinstance(variants, list) and any(
                not isinstance(item, dict) for item in variants
            ):
                raise ValueError("Variants must contain supported schemas")
            if "object" in types:
                required = node.get("required")
                if (
                    not isinstance(properties, dict)
                    or node.get("additionalProperties") is not False
                    or not isinstance(required, list)
                    or set(required) != set(properties)
                ):
                    raise ValueError(
                        "Strict objects require every property and forbid extras"
                    )
                properties_count += len(properties)
                string_length += sum(map(len, properties))
            enum = node.get("enum", [])
            if isinstance(enum, list):
                enum_count += len(enum)
                enum_length = sum(
                    len(value) for value in enum if isinstance(value, str)
                )
                string_length += enum_length
                if len(enum) > 250 and enum_length > 15_000:
                    raise ValueError("Enum size limit")
            definitions = node.get("$defs", {})
            if isinstance(definitions, dict):
                string_length += sum(map(len, definitions))
            const = node.get("const")
            if isinstance(const, str):
                string_length += len(const)
        if properties_count > 5000 or enum_count > 1000 or string_length > 120_000:
            raise ValueError("Schema size limit")

        def depth(node: dict[str, JsonValue], level: int, seen: frozenset[str]) -> None:
            ref = node.get("$ref")
            if isinstance(ref, str) and ref not in seen:
                depth(_resolve(data, ref), level, seen | {ref})
            types = node.get("type")
            types = types if isinstance(types, list) else [types]
            level += int("object" in types or "array" in types)
            if level > 10:
                raise ValueError("Schema depth limit")
            properties = node.get("properties", {})
            if isinstance(properties, dict):
                for child in properties.values():
                    if isinstance(child, dict):
                        depth(child, level, seen)
            items = node.get("items")
            if isinstance(items, dict):
                depth(items, level, seen)
            variants = node.get("anyOf", [])
            if isinstance(variants, list):
                for child in variants:
                    if isinstance(child, dict):
                        depth(child, level, seen)

        depth(data, 0, frozenset())
    except Exception:
        raise StructuredOutputValidationError("unsupported_schema") from None


def validate_structured_output(
    content: str,
    plan: StructuredOutputPlan,
    model: type[BaseModel] | None = None,
) -> BaseModel | FrozenJsonValue:
    """Reject duplicate keys/nonfinite values before JSON Schema or model coercion."""
    try:
        value = parse_json(content, "structured output")
    except (ValueError, RecursionError):
        raise StructuredOutputValidationError("invalid_json") from None
    try:
        schema_validator(plan.schema).evolve(format_checker=FormatChecker()).validate(
            value
        )
        if model is not None:
            # JSON strictness accepts enum/date strings but never coerces verdicts.
            return model.model_validate_json(content, strict=True)
        return freeze(value)
    except Exception:
        raise StructuredOutputValidationError("schema_mismatch") from None
