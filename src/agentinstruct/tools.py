"""Public Tool contract, function adapter, and actor-aware execution inputs."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from jsonschema.protocols import Validator
from jsonschema.validators import validator_for
from pydantic import TypeAdapter
from referencing import Registry

from agentinstruct.plans import (
    FrozenJsonValue,
    JsonSchema,
    JsonValue,
    TaskIdentity,
    ToolPlan,
    canonical_json,
    json_value,
)
from agentinstruct.traces import immutable_data


@dataclass(frozen=True)
class ToolContext:
    actor_id: str
    task: TaskIdentity
    seed_id: str
    variables: Mapping[str, FrozenJsonValue]
    run_id: str
    trace_id: str
    turn_id: str = ""
    tool_call_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "variables", immutable_data(self.variables))


class Tool(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def input_schema(self) -> JsonSchema: ...

    @property
    def output_schema(self) -> JsonSchema | None: ...

    @property
    def execution_errors(self) -> Literal["fail", "result"]: ...

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue: ...


type ToolFunction = Callable[
    [Mapping[str, FrozenJsonValue], ToolContext], Awaitable[JsonValue]
]


class FunctionTool:
    """Adapt an async function receiving structured arguments and ToolContext."""

    def __init__(self, plan: ToolPlan, function: ToolFunction) -> None:
        self.id = plan.id
        self.description = plan.description
        self.input_schema = plan.input_schema
        self.output_schema = plan.output_schema
        self.execution_errors = plan.execution_errors
        self.function = function

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        return await self.function(args, context)


def create_tool(plan: ToolPlan) -> Tool:
    raise ValueError(f"Tool {plan.id!r} requires a tool_factory")


class ToolError(RuntimeError):
    def __init__(
        self,
        kind: Literal["assignment", "arguments", "execution", "result", "unsupported"],
    ) -> None:
        self.kind = kind
        super().__init__(f"Tool {kind} failed")


@dataclass(frozen=True)
class ToolExecutionFailure:
    """Fixed error-result contract; exception text is never Agent-visible."""

    exception: str
    kind: Literal["execution"] = "execution"


def schema_validator(schema: JsonSchema) -> Validator:
    """Compile a declared schema with an offline-only reference registry."""
    data = json_value(schema)
    assert isinstance(data, (dict, bool))
    validator_class = validator_for(data)
    if not isinstance(data, bool):
        validator_class.check_schema(data)
    # Explicit Registry defaults to no retrieval; schemas never trigger HTTP I/O.
    return validator_class(data, registry=Registry())


def validate_tool_data(value: object, schema: JsonSchema) -> None:
    schema_validator(schema).validate(json_value(value))


def tool_result_content(result: JsonValue, schema: JsonSchema | None) -> str:
    """Require JSON data even when the Tool has no additional output schema."""
    validated: JsonValue = TypeAdapter(JsonValue).validate_python(result, strict=True)
    if schema is not None:
        validate_tool_data(validated, schema)
    return canonical_json(validated)
