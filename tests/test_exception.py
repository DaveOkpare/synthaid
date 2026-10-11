from synthaid import exception
from synthaid import message

_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)


def test_unknown_tool_error_names_the_tool() -> None:
    error = exception.UnknownToolError(_CALL)

    assert isinstance(error, exception.ToolError)
    assert error.call == _CALL
    assert "get_weather" in str(error)


def test_tool_execution_error_names_the_tool_and_call() -> None:
    error = exception.ToolExecutionError(_CALL)

    assert isinstance(error, exception.ToolError)
    assert error.call == _CALL
    assert "get_weather" in str(error)
    assert "call-1" in str(error)


def test_tool_rounds_error_names_the_limit() -> None:
    error = exception.ToolRoundsError(10)

    assert error.max_tool_rounds == 10
    assert "10" in str(error)
