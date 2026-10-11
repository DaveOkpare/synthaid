import pathlib

import pytest

from synthaid import agent
from synthaid import config
from synthaid import environment
from synthaid import evaluation
from synthaid import message
from tests import fakes

_BASIC = """\
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
max_turns = 2
"""


def _write(directory: pathlib.Path, text: str = _BASIC) -> pathlib.Path:
    path = directory / "tasks.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_builds_fresh_tasks_from_tables(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")
    definitions = config.load(_write(tmp_path))

    first = definitions.build("first")
    second = definitions.build("first")

    assert definitions.task_names == ("first",)
    assert first.steps[0].instruction == "Say hello."
    assert first.steps[0].max_turns == 2
    assert first.user is None
    assert first.assistant is not second.assistant
    first.assistant.model = fakes.scripted(message.Message("assistant", "Hi."))
    environment.run(first)
    assert first.chat_history[-1].text == "Hi."
    assert second.chat_history == []
    assert second.assistant.logs == []


def test_validation_does_not_resolve_credentials_or_import_tools(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SYNTHAID_CONFIG_TEST_KEY", raising=False)
    (tmp_path / "tools.py").write_text("raise RuntimeError('imported')\n")
    text = _BASIC.replace(
        'instructions = "Be helpful."',
        'instructions = "Be helpful."\ntools = ["weather"]',
    )
    text += '\n[tools.weather]\nfile = "tools.py"\nobject = "WEATHER"\n'

    assert config.load(_write(tmp_path, text)).task_names == ("first",)


def test_tool_file_resolves_relative_to_config_and_runs(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")
    (tmp_path / "tools.py").write_text(
        "from synthaid import tool\n"
        'WEATHER = tool.Tool("get_weather", "Weather", {}, '
        'lambda city: {"city": city, "temperature": 31})\n'
    )
    text = _BASIC.replace(
        'instructions = "Be helpful."',
        'instructions = "Be helpful."\ntools = ["weather"]',
    )
    text += '\n[tools.weather]\nfile = "tools.py"\nobject = "WEATHER"\n'
    path = _write(tmp_path, text)
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    built = config.load(path).build("first")
    call = message.ToolCall("call-1", "get_weather", {"city": "Lagos"})
    built.assistant.model = fakes.scripted(
        message.Message("assistant", None, tool_calls=(call,)),
        message.Message("assistant", "It is 31°C."),
    )

    environment.run(built)

    assert built.chat_history[2].role == "tool"
    assert '"temperature": 31' in built.chat_history[2].text
    assert built.chat_history[-1].text == "It is 31°C."


def test_criteria_tables_build_fresh_judges_for_each_agent(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")
    text = _BASIC.replace(
        'instructions = "Be helpful."',
        'instructions = "Be helpful."\nevaluator = "quality"',
    ).replace(
        'assistant = "assistant"',
        'assistant = "assistant"\nuser = "traveller"',
    )
    text += """
[agents.traveller]
model = "gpt"
instructions = "Act as a traveller."
evaluator = "quality"

[evaluators.quality]
kind = "llm"
model = "gpt"
threshold = 1.0
instructions = "Check these criteria."

[[evaluators.quality.criteria]]
content = "Is concise."
weight = 2.0

[[evaluators.quality.criteria]]
content = "Invents facts."
weight = -1.0
"""
    definitions = config.load(_write(tmp_path, text))
    first = definitions.build("first")
    second = definitions.build("first")

    judge = first.assistant.evaluator
    assert isinstance(judge, evaluation.LLMJudge)
    assert [item.weight for item in judge.criteria] == [2.0, -1.0]
    assert judge.instructions == "Check these criteria."
    judge.model = fakes.scripted(
        message.Message(
            "assistant",
            evaluation.Verdict(
                answers=[
                    evaluation.Answer(
                        content=item.content, met=evaluation.Met.YES
                    )
                    for item in judge.criteria
                ],
                feedback="Both are present.",
            ),
        )
    )
    # Score 2 - 1 passes the configured threshold 1, but not the default 2.
    assert judge(agent.Draft(message.Message("assistant", "Draft."), [])).passed
    assert first.user is not None
    assert judge is not first.user.evaluator
    assert judge is not second.assistant.evaluator


@pytest.mark.parametrize(
    ("old", "new", "field"),
    [
        ("schema_version = 1", "schema_version = 2", "schema_version"),
        ("schema_version = 1", "schema_version = true", "schema_version"),
        ('model = "gpt"', 'model = "missing"', "agents.assistant.model"),
        ("max_turns = 2", "max_turns = 0", "tasks.first.steps.0.max_turns"),
        ("max_turns = 2", "max_turns = true", "tasks.first.steps.0.max_turns"),
        (
            'instructions = "Be helpful."',
            'instructions = "Be helpful."\nmax_iterations = 0',
            "agents.assistant.max_iterations",
        ),
        (
            'instructions = "Be helpful."',
            'instructions = "Be helpful."\nmax_iteratons = 3',
            "agents.assistant.max_iteratons",
        ),
        (
            'assistant = "assistant"',
            'assistant = "missing"',
            "tasks.first.assistant",
        ),
        (
            'assistant = "assistant"',
            'assistant = "assistant"\nuser = "assistant"',
            "tasks.first.user",
        ),
        (
            'instructions = "Be helpful."',
            'instructions = "Be helpful."\ntools = ["missing"]',
            "agents.assistant.tools.0",
        ),
        (
            'instructions = "Be helpful."',
            'instructions = "Be helpful."\nevaluator = "missing"',
            "agents.assistant.evaluator",
        ),
    ],
)
def test_validation_reports_field_paths(
    tmp_path: pathlib.Path, old: str, new: str, field: str
) -> None:
    with pytest.raises(config.ConfigError) as caught:
        config.load(_write(tmp_path, _BASIC.replace(old, new)))
    assert field in str(caught.value)


def test_validation_rejects_empty_tasks(tmp_path: pathlib.Path) -> None:
    with pytest.raises(config.ConfigError, match="tasks"):
        config.load(_write(tmp_path, _BASIC.split("[tasks.first]")[0]))


def test_validation_rejects_duplicate_criteria(tmp_path: pathlib.Path) -> None:
    text = (
        _BASIC
        + """
[evaluators.quality]
kind = "llm"
model = "gpt"
[[evaluators.quality.criteria]]
content = "Is concise."
[[evaluators.quality.criteria]]
content = "Is concise."
"""
    )
    with pytest.raises(
        config.ConfigError, match=r"evaluators\.quality\.criteria"
    ):
        config.load(_write(tmp_path, text))


def test_validation_rejects_missing_tool_file(tmp_path: pathlib.Path) -> None:
    text = _BASIC + '\n[tools.weather]\nfile = "missing.py"\nobject = "X"\n'
    with pytest.raises(config.ConfigError, match=r"tools\.weather\.file"):
        config.load(_write(tmp_path, text))


def test_validation_rejects_ambiguous_python_reference(
    tmp_path: pathlib.Path,
) -> None:
    text = (
        _BASIC
        + """
[tools.weather]
file = "tools.py"
module = "tools"
object = "WEATHER"
"""
    )
    with pytest.raises(config.ConfigError, match=r"tools\.weather"):
        config.load(_write(tmp_path, text))


def test_build_reports_missing_credentials_without_values(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SYNTHAID_CONFIG_TEST_KEY", raising=False)
    definitions = config.load(_write(tmp_path))
    with pytest.raises(config.ConfigError, match="SYNTHAID_CONFIG_TEST_KEY"):
        definitions.build("first")


def test_build_rejects_non_tool_python_object(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")
    (tmp_path / "tools.py").write_text("WEATHER = 42\n")
    text = _BASIC.replace(
        'instructions = "Be helpful."',
        'instructions = "Be helpful."\ntools = ["weather"]',
    )
    text += '\n[tools.weather]\nfile = "tools.py"\nobject = "WEATHER"\n'
    with pytest.raises(config.ConfigError, match=r"tools\.weather"):
        config.load(_write(tmp_path, text)).build("first")


def test_build_reports_unknown_task(tmp_path: pathlib.Path) -> None:
    with pytest.raises(config.ConfigError, match="unknown task 'missing'"):
        config.load(_write(tmp_path)).build("missing")


def test_model_defaults_to_openai_key(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "unused-default")
    text = _BASIC.replace('api_key_env = "SYNTHAID_CONFIG_TEST_KEY"\n', "")
    built = config.load(_write(tmp_path, text)).build("first")

    assert built.assistant.model.api_key == "unused-default"
    assert built.assistant.model.temperature == 0.7


def test_importable_module_reference(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SYNTHAID_CONFIG_TEST_KEY", "unused")
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "synthaid_test_tools.py").write_text(
        "from synthaid import tool\n"
        'WEATHER = tool.Tool("weather", "Weather", {}, lambda: "sunny")\n'
    )
    text = _BASIC.replace(
        'instructions = "Be helpful."',
        'instructions = "Be helpful."\ntools = ["weather"]',
    )
    text += (
        '\n[tools.weather]\nmodule = "synthaid_test_tools"\n'
        'object = "WEATHER"\n'
    )

    built = config.load(_write(tmp_path, text)).build("first")

    assert (
        built.assistant.tools[0](message.ToolCall("id", "weather", {})).text
        == "sunny"
    )


def test_unknown_credential_field_does_not_expose_its_value(
    tmp_path: pathlib.Path,
) -> None:
    text = _BASIC.replace(
        'model_name = "test-model"',
        'model_name = "test-model"\napi_key = "private-value"',
    )

    with pytest.raises(config.ConfigError) as caught:
        config.load(_write(tmp_path, text))

    assert "models.gpt.api_key" in str(caught.value)
    assert "private-value" not in str(caught.value)


def test_load_reports_invalid_toml(tmp_path: pathlib.Path) -> None:
    with pytest.raises(config.ConfigError, match=r"tasks\.toml"):
        config.load(_write(tmp_path, "[broken"))


def test_discovery_sorts_files_and_makes_recursion_explicit(
    tmp_path: pathlib.Path,
) -> None:
    for name in ("b.toml", "a.toml", "tools.py"):
        (tmp_path / name).touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "c.toml").touch()
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "hidden.toml").touch()
    root = tmp_path / "runs"
    root.mkdir()
    (root / "saved.toml").touch()

    assert config.discover(tmp_path, exclude=root) == [
        tmp_path / "a.toml",
        tmp_path / "b.toml",
    ]
    assert config.discover(tmp_path, recursive=True, exclude=root) == [
        tmp_path / "a.toml",
        tmp_path / "b.toml",
        nested / "c.toml",
    ]


def test_discovery_rejects_empty_directory(tmp_path: pathlib.Path) -> None:
    with pytest.raises(config.ConfigError, match="No TOML task files"):
        config.discover(tmp_path)
