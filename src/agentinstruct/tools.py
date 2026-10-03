"""Callable Tools validate arguments and results at their capability boundary."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import FormatChecker
from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from referencing import Registry

from agentinstruct.episode import freeze, json_data


class ToolError(RuntimeError):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Tool {kind} failed")


def schema_validator(schema: Any) -> Validator:
    data = json_data(schema)
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
        object.__setattr__(self, "input_schema", freeze(schema))
        if self.output_schema is not None:
            schema_validator(self.output_schema)
            object.__setattr__(self, "output_schema", freeze(self.output_schema))

    def validate(self, arguments: Mapping[str, Any]) -> None:
        try:
            if not isinstance(arguments, Mapping):
                raise ValueError("Tool arguments must be an object")
            schema_validator(self.input_schema).validate(json_data(arguments))
        except Exception as exc:
            raise ToolError("arguments") from exc

    async def call(self, arguments: Mapping[str, Any]) -> Any:
        self.validate(arguments)
        try:
            value = await self.function(freeze(arguments))
        except Exception as exc:
            if self.execution_errors == "result":
                return {"error": {"exception": type(exc).__name__, "kind": "execution"}}
            raise ToolError("execution") from exc
        return self.validate_result(value)

    def validate_result(self, value: Any) -> Any:
        try:
            data = json_data(value)
            if self.output_schema is not None:
                schema_validator(self.output_schema).validate(data)
            return data
        except Exception as exc:
            raise ToolError("result") from exc

    def declaration(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "input_schema": json_data(self.input_schema),
            "output_schema": json_data(self.output_schema),
            "execution_errors": self.execution_errors,
        }
