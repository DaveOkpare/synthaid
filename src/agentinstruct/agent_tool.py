"""Adapt a fresh, isolated subordinate Agent to the public Tool contract."""

import json
from collections.abc import Callable, Mapping

from pydantic import TypeAdapter

from agentinstruct.execution import Agent, Observation
from agentinstruct.plans import FrozenJsonValue, JsonValue, ToolPlan, canonical_json
from agentinstruct.tools import (
    ToolContext,
    ToolError,
    tool_result_content,
    validate_tool_data,
)
from agentinstruct.traces import Message


class AgentTool:
    """Use one fresh Agent proposal as JSON output, without nested effects.

    The factory must return a new Agent for every invocation. The subordinate
    receives only the supplied instruction and current arguments; no participant
    history, Tool assignments, or parent control authority is inherited.
    """

    def __init__(
        self,
        plan: ToolPlan,
        agent_factory: Callable[[], Agent],
        *,
        instruction: str,
    ) -> None:
        self.id = plan.id
        self.description = plan.description
        self.input_schema = plan.input_schema
        self.output_schema = plan.output_schema
        self.execution_errors = plan.execution_errors
        self.agent_factory = agent_factory
        self.instruction = instruction
        self._agent_reference = plan.agent_factory or plan.id

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        try:
            validate_tool_data(args, self.input_schema)
        except Exception as exc:
            raise ToolError("arguments") from exc
        from agentinstruct.components import ComponentError, validate_component

        try:
            agent = self.agent_factory()
        except Exception as exc:
            raise ComponentError(
                "AgentTool factory",
                self._agent_reference,
                f"construction failed ({type(exc).__name__})",
            ) from None
        validate_component("agent", agent, self._agent_reference)
        action = await agent.generate(
            Observation(
                self.id,
                self.instruction,
                (Message("user", canonical_json(args)),),
            )
        )
        messages = action if isinstance(action, list) else [action]
        if any(
            isinstance(message, Message)
            and (
                message.tool_calls
                or message.control is not None
                or message.tool_call_id is not None
            )
            for message in messages
        ):
            raise ToolError("unsupported")
        try:
            if len(messages) != 1 or not isinstance(messages[0], Message):
                raise ValueError("Agent Tool requires one JSON reply Message")
            message = messages[0]
            if message.role != "assistant":
                raise ValueError("Agent Tool requires an assistant reply")
            result: JsonValue = TypeAdapter(JsonValue).validate_python(
                json.loads(message.content), strict=True
            )
            tool_result_content(result, self.output_schema)
            return result
        except Exception as exc:
            raise ToolError("result") from exc
