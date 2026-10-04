"""Callable Tools validate arguments and results at their capability boundary."""

import json
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import FormatChecker
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry


class ToolError(RuntimeError):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Tool {kind} failed")


def schema_validator(schema: Any) -> Validator:
    data = deepcopy(schema)
    json.dumps(data, allow_nan=False)
    if not isinstance(data, (dict, bool)):
        raise ValueError("Schema must be an object or Boolean")
    cls = validator_for(data)
    if isinstance(data, dict):
        cls.check_schema(data)
    return cls(data, registry=Registry(), format_checker=FormatChecker())


@dataclass(frozen=True)
class Tool:
    function: Callable[[Mapping[str, Any]], Awaitable[Any]]
    id: str = ""
    description: str = ""
    input_schema: Any = None
    output_schema: Any = None
    execution_errors: Literal["fail", "result"] = "fail"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "id", self.id or getattr(self.function, "__name__", "")
        )
        if (
            not isinstance(self.id, str)
            or not self.id.strip()
            or not callable(self.function)
        ):
            raise ValueError("Tool needs an identifier and callable")
        if self.execution_errors not in {"fail", "result"}:
            raise ValueError("Tool execution_errors must be fail or result")
        schema = {"type": "object"} if self.input_schema is None else self.input_schema
        schema_validator(schema)
        object.__setattr__(self, "input_schema", deepcopy(schema))
        if self.output_schema is not None:
            schema_validator(self.output_schema)
            object.__setattr__(self, "output_schema", deepcopy(self.output_schema))

    def validate(self, arguments: Mapping[str, Any]) -> None:
        try:
            if not isinstance(arguments, Mapping):
                raise ValueError("Tool arguments must be an object")
            json.dumps(dict(arguments), allow_nan=False)
            schema_validator(self.input_schema).validate(arguments)
        except Exception as exc:
            raise ToolError("arguments") from exc

    async def call(self, arguments: Mapping[str, Any]) -> Any:
        self.validate(arguments)
        try:
            value = await self.function(deepcopy(dict(arguments)))
        except Exception as exc:
            if self.execution_errors == "result":
                return {"error": {"exception": type(exc).__name__, "kind": "execution"}}
            raise ToolError("execution") from exc
        return self.validate_result(value)

    def validate_result(self, value: Any) -> Any:
        try:
            json.dumps(value, allow_nan=False)
            if self.output_schema is not None:
                schema_validator(self.output_schema).validate(value)
            return value
        except Exception as exc:
            raise ToolError("result") from exc

    def declaration(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "input_schema": deepcopy(self.input_schema),
            "output_schema": deepcopy(self.output_schema),
            "execution_errors": self.execution_errors,
        }
