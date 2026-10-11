from collections.abc import Sequence
import json
import pathlib

import httpx
import openai
import pydantic
import pytest

from synthaid import cli
from synthaid import export
from synthaid import message
from synthaid import model
from synthaid import tool

_TASK = """\
schema_version = 1
[models.gpt]
model_name = "test-model"
base_url = "http://unused"
api_key_env = "SYNTHAID_CONFIG_TEST_KEY"
[agents.assistant]
model = "gpt"
instructions = "Be helpful."
[tasks.first]
assistant = "assistant"
[[tasks.first.steps]]
instruction = "Say hello."
"""


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")

    def generate(
        self: model.Model,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        seen.append(messages[-1].text)
        if messages[-1].text == "fail":
            raise RuntimeError("provider unavailable")
        return message.Message("assistant", "Hello.")

    monkeypatch.setattr(model.Model, "generate", generate)
    return seen


def test_validate_needs_no_credentials_and_creates_no_runs(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("SYNTHAID_CONFIG_TEST_KEY", raising=False)
    path = tmp_path / "task.toml"
    path.write_text(_TASK)
    root = tmp_path / "runs"

    assert cli.main(["validate", str(path), "--root", str(root)]) == 0
    assert "first" in capsys.readouterr().out
    assert not root.exists()


def test_run_directory_saves_every_task_in_sorted_order(
    tmp_path: pathlib.Path,
    requests: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "b.toml").write_text(_TASK.replace("hello", "goodbye"))
    (tmp_path / "a.toml").write_text(
        _TASK
        + """
[tasks.second]
assistant = "assistant"
[[tasks.second.steps]]
instruction = "Say goodnight."
"""
    )
    (tmp_path / "tools.py").write_text("raise RuntimeError('not a task')\n")
    root = tmp_path / "runs"

    assert cli.main(["run", str(tmp_path), "--root", str(root)]) == 0

    assert requests == ["Say hello.", "Say goodnight.", "Say goodbye."]
    assert len(list(root.glob("*/exchange.json"))) == 3
    transcripts = sorted(root.glob("*/exchange.txt"))
    assert len(transcripts) == 3
    assert all("[assistant] Hello." in path.read_text() for path in transcripts)
    assert len(list(root.glob("*/logs/assistant.json"))) == 3
    output = capsys.readouterr().out
    assert output.index("a.toml:first") < output.index("b.toml:first")
    assert "[assistant]" not in output
    assert "3 completed, 0 failed" in output


def test_invalid_later_file_prevents_all_execution(
    tmp_path: pathlib.Path,
    requests: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.toml").write_text(_TASK)
    (tmp_path / "b.toml").write_text(
        _TASK.replace('model = "gpt"', 'model = "unknown"')
    )
    root = tmp_path / "runs"

    assert cli.main(["run", str(tmp_path), "--root", str(root)]) == 2

    assert requests == []
    assert not root.exists()
    assert "agents.assistant.model" in capsys.readouterr().err


def test_missing_credential_in_later_file_prevents_all_execution(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    requests: list[str],
) -> None:
    monkeypatch.delenv("SYNTHAID_MISSING_TEST_KEY", raising=False)
    (tmp_path / "a.toml").write_text(_TASK)
    (tmp_path / "b.toml").write_text(
        _TASK.replace("SYNTHAID_CONFIG_TEST_KEY", "SYNTHAID_MISSING_TEST_KEY")
    )

    assert cli.main(["run", str(tmp_path)]) == 2
    assert requests == []


def test_failed_run_is_saved_and_batch_continues(
    tmp_path: pathlib.Path,
    requests: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "a.toml").write_text(_TASK.replace("Say hello.", "fail"))
    (tmp_path / "b.toml").write_text(_TASK)
    root = tmp_path / "runs"

    assert cli.main(["run", str(tmp_path), "--root", str(root)]) == 1

    assert requests == ["fail", "Say hello."]
    assert len(list(root.glob("*/exchange.json"))) == 2
    assert len(list(root.glob("*/logs/assistant.json"))) == 2
    assert "[user] fail\n" in [
        path.read_text() for path in root.glob("*/exchange.txt")
    ]
    assert "provider unavailable" in capsys.readouterr().err


def test_task_selection_runs_only_the_selected_task(
    tmp_path: pathlib.Path, requests: list[str]
) -> None:
    path = tmp_path / "tasks.toml"
    path.write_text(
        _TASK
        + """
[tasks.second]
assistant = "assistant"
[[tasks.second.steps]]
instruction = "Say goodbye."
"""
    )

    assert (
        cli.main(
            [
                "run",
                str(path),
                "--task",
                "second",
                "--root",
                str(tmp_path / "runs"),
            ]
        )
        == 0
    )
    assert requests == ["Say goodbye."]


def test_task_selection_requires_a_file(
    tmp_path: pathlib.Path, requests: list[str]
) -> None:
    (tmp_path / "tasks.toml").write_text(_TASK)

    assert cli.main(["run", str(tmp_path), "--task", "first"]) == 2
    assert requests == []


def test_interrupt_saves_partial_run(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")
    path = tmp_path / "tasks.toml"
    path.write_text(_TASK)
    root = tmp_path / "runs"

    def interrupt(
        self: model.Model,
        messages: Sequence[message.Message],
        *,
        tools: Sequence[tool.Tool] = (),
        output_type: type[str] | type[pydantic.BaseModel] = str,
    ) -> message.Message:
        raise KeyboardInterrupt

    monkeypatch.setattr(model.Model, "generate", interrupt)

    assert cli.main(["run", str(path), "--root", str(root)]) == 130
    assert len(list(root.glob("*/exchange.json"))) == 1
    (transcript,) = root.glob("*/exchange.txt")
    assert transcript.read_text() == "[user] Say hello.\n"


def test_unknown_task_has_a_readable_error(
    tmp_path: pathlib.Path,
    requests: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "tasks.toml"
    path.write_text(_TASK)

    assert cli.main(["run", str(path), "--task", "missing"]) == 2
    assert requests == []
    assert "unknown task 'missing'" in capsys.readouterr().err


def test_save_failure_returns_nonzero(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    requests: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "tasks.toml"
    path.write_text(_TASK)

    def fail_save(*args: object) -> pathlib.Path:
        raise OSError("disk full")

    monkeypatch.setattr(export, "save", fail_save)

    assert cli.main(["run", str(path), "--root", str(tmp_path / "runs")]) == 1
    assert requests == ["Say hello."]
    assert "failed to save" in capsys.readouterr().err


def test_weather_toml_runs_simulator_judge_and_real_tool(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = pathlib.Path(__file__).resolve().parents[1] / "examples/weather.toml"
    monkeypatch.setenv("DOUBLEWORD_API_KEY", "unused")

    def complete(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        messages = body["messages"]
        reply: dict[str, object] = {"role": "assistant"}
        if "response_format" in body:
            criteria = json.loads(
                messages[-1]["content"]
                .split("Criteria:\n", 1)[1]
                .split("\n\n", 1)[0]
            )
            reply["content"] = json.dumps(
                {
                    "answers": [
                        {
                            "content": content,
                            "met": "yes" if index == 0 else "no",
                        }
                        for index, content in enumerate(criteria)
                    ],
                    "feedback": "Matches the tool result.",
                }
            )
        elif body.get("tools"):
            if messages[-1]["role"] == "tool":
                reply["content"] = "It is 31°C in Lagos."
            else:
                reply["content"] = None
                reply["tool_calls"] = [
                    {
                        "id": f"call-{len(messages)}",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps({"city": "Lagos"}),
                        },
                    }
                ]
        else:
            reply["content"] = "What is the weather in Lagos?"
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "created": 0,
                "object": "chat.completion",
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls"
                        if "tool_calls" in reply
                        else "stop",
                        "message": reply,
                    }
                ],
            },
        )

    with openai.OpenAI(
        api_key="unused",
        http_client=httpx.Client(transport=httpx.MockTransport(complete)),
    ) as client:
        monkeypatch.setattr(
            model.Model, "_client", property(lambda self: client)
        )
        assert cli.main(["run", str(path), "--root", str(tmp_path)]) == 0

    (saved,) = tmp_path.glob("*/exchange.json")
    record = json.loads(saved.read_text())
    assert (
        len([item for item in record["messages"] if item["role"] == "user"])
        == 3
    )
    results = [item for item in record["messages"] if item["role"] == "tool"]
    assert len(results) == 3
    assert json.loads(results[0]["content"])["forecast"] == "31°C, humid, clear"
    assert (saved.parent / "logs/user.json").is_file()
    assert (saved.parent / "logs/assistant-evaluator.json").is_file()
    transcript = (saved.parent / "exchange.txt").read_text(encoding="utf-8")
    assert "[assistant] calls get_weather(" in transcript
    assert "[assistant] It is 31°C in Lagos." in transcript
    assert "get_weather" not in capsys.readouterr().out
