"""Errors raised by synthaid."""

from synthaid import message


class ToolError(Exception):
    """Base class for errors raised while handling a tool call.

    Attributes:
        call: The tool call that failed.
    """

    def __init__(self, call: message.ToolCall, detail: str) -> None:
        """Stores the call and builds the error message from `detail`."""
        super().__init__(detail)
        self.call = call


class UnknownToolError(ToolError):
    """The model asked for a tool the agent does not have."""

    def __init__(self, call: message.ToolCall) -> None:
        """Stores the call and builds a message naming the tool."""
        super().__init__(call, f"Unknown tool: {call.name!r}")


class ToolExecutionError(ToolError):
    """A tool's function raised an exception.

    The original exception is chained as `__cause__`.
    """

    def __init__(self, call: message.ToolCall) -> None:
        """Stores the call and builds a message naming the tool and call."""
        super().__init__(
            call, f"Tool {call.name!r} failed for call {call.id!r}"
        )


class ToolRoundsError(Exception):
    """A turn asked for more rounds of tool calls than the agent allows.

    Attributes:
        max_tool_rounds: The agent's limit.
    """

    def __init__(self, max_tool_rounds: int) -> None:
        """Stores the limit and builds a message naming it."""
        super().__init__(
            f"More than {max_tool_rounds} rounds of tool calls in one turn"
        )
        self.max_tool_rounds = max_tool_rounds
