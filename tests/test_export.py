import json
import pathlib
from typing import Any

import pydantic

from synthaid import agent
from synthaid import evaluation
from synthaid import export
from synthaid import message
from synthaid import model
from synthaid import task
from synthaid import tool
from tests import fakes

_MODEL = model.Model("test-model", "http://localhost")
_STEP = task.Step("Ask about the weather in Lagos.")
_CALL = message.ToolCall(
    id="call-1", name="get_weather", arguments={"city": "Lagos"}
)
_WEATHER = tool.Tool(
    name="get_weather",
    description="Gets the weather for a city.",
    parameters={"type": "object"},
    function=lambda city: "31°C",
)


class _Forecast(pydantic.BaseModel):
    city: str


def _read(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _task(
    history: list[message.Message], tools: list[tool.Tool] | None = None
) -> task.Task:
    assistant = agent.Agent(_MODEL, "Be helpful.", tools=tools or [])
    return task.Task(assistant, [_STEP], chat_history=history)


def test_record_has_system_message_history_and_tools() -> None:
    finished = _task(
        [
            message.Message("user", "Weather in Lagos?"),
            message.Message("assistant", None, tool_calls=(_CALL,)),
            message.Message("tool", "31°C", tool_call_id="call-1"),
            message.Message("assistant", "It is 31°C."),
        ],
        tools=[_WEATHER],
    )

    assert export.to_record(finished) == {
        "messages": [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Weather in Lagos?"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Lagos"}',
                        },
                    }
                ],
            },
            {"role": "tool", "content": "31°C", "tool_call_id": "call-1"},
            {"role": "assistant", "content": "It is 31°C."},
        ],
        "tools": [_WEATHER.to_chat_completions()],
    }


def test_record_keeps_reasoning_as_reasoning_content() -> None:
    finished = _task(
        [
            message.Message("user", "Hi.", reasoning="Open casually."),
            message.Message("assistant", "Hello.", reasoning="Greet back."),
        ]
    )

    user, reply = export.to_record(finished)["messages"][1:]

    assert user["reasoning_content"] == "Open casually."
    assert reply["reasoning_content"] == "Greet back."


def test_record_leaves_out_missing_reasoning_and_tools() -> None:
    record = export.to_record(_task([message.Message("user", "Hi.")]))

    assert "tools" not in record
    assert all("reasoning_content" not in item for item in record["messages"])


def test_record_writes_structured_content_as_json() -> None:
    finished = _task(
        [
            message.Message("user", "Forecast?"),
            message.Message("assistant", _Forecast(city="Lagos")),
        ]
    )

    reply = export.to_record(finished)["messages"][-1]

    assert reply["content"] == '{"city":"Lagos"}'


def test_write_jsonl_appends_one_record_per_task(
    tmp_path: pathlib.Path,
) -> None:
    path = tmp_path / "traces.jsonl"
    first = _task([message.Message("user", "One.")])
    second = _task([message.Message("user", "Two°C.")])

    export.write_jsonl([first], path)
    export.write_jsonl([second], path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == [
        export.to_record(first),
        export.to_record(second),
    ]
    # Text is written as is, not as \u escapes.
    assert "Two°C." in lines[1]


def test_save_creates_a_new_directory_for_each_task(
    tmp_path: pathlib.Path,
) -> None:
    finished = _task([message.Message("user", "Hi.")])

    first = export.save(finished, tmp_path / "runs")
    second = export.save(finished, tmp_path / "runs")

    assert first != second
    assert first.parent == second.parent == tmp_path / "runs"


def test_save_writes_the_exchange_record(tmp_path: pathlib.Path) -> None:
    finished = _task(
        [message.Message("user", "Hi."), message.Message("assistant", "Yo.")],
        tools=[_WEATHER],
    )

    directory = export.save(finished, tmp_path)

    assert _read(directory / "exchange.json") == export.to_record(finished)


def test_save_writes_each_agent_logs(tmp_path: pathlib.Path) -> None:
    assistant = agent.Agent(
        fakes.scripted(
            message.Message("assistant", "Sunny.", reasoning="Easy.")
        ),
        "Be helpful.",
    )
    user = agent.Agent(
        fakes.scripted(message.Message("assistant", "Weather?")),
        "Act as a user.",
    )
    asked = user.run([message.Message("user", "Start.")])
    assistant.run([message.Message("user", asked[-1].text)])

    directory = export.save(task.Task(assistant, [_STEP], user=user), tmp_path)

    assert _read(directory / "logs" / "assistant.json") == [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Weather?"},
        {
            "role": "assistant",
            "content": "Sunny.",
            "reasoning_content": "Easy.",
        },
    ]
    assert _read(directory / "logs" / "user.json") == [
        {"role": "system", "content": "Act as a user."},
        {"role": "user", "content": "Start."},
        {"role": "assistant", "content": "Weather?"},
    ]


def test_save_leaves_out_missing_user(tmp_path: pathlib.Path) -> None:
    directory = export.save(_task([]), tmp_path)

    assert sorted(item.name for item in (directory / "logs").iterdir()) == [
        "assistant.json"
    ]


def test_save_writes_evaluator_logs_when_it_is_an_agent(
    tmp_path: pathlib.Path,
) -> None:
    criterion = evaluation.Criterion(content="Is short.")
    verdict = evaluation.Verdict(
        answers=[
            evaluation.Answer(content="Is short.", met=evaluation.Met.YES)
        ],
        feedback="Fine.",
    )
    judge = evaluation.LLMJudge(
        fakes.scripted(message.Message("assistant", verdict)), [criterion]
    )
    judge(agent.Draft(message.Message("assistant", "Sunny."), context=[]))
    assistant = agent.Agent(_MODEL, "Be helpful.", evaluator=judge)

    directory = export.save(task.Task(assistant, [_STEP]), tmp_path)

    logs = _read(directory / "logs" / "assistant-evaluator.json")
    assert [item["role"] for item in logs] == ["system", "user", "assistant"]
    assert json.loads(logs[-1]["content"])["feedback"] == "Fine."
