import pytest

from synthaid import agent
from synthaid import message
from synthaid import model
from synthaid import task

_MODEL = model.Model("test-model", "http://localhost")
_STEP = task.Step("Ask about the weather in Lagos.")


def _agent() -> agent.Agent:
    return agent.Agent(_MODEL, "Be helpful.")


def test_step_defaults_to_one_turn() -> None:
    assert task.Step("Say hello.").max_turns == 1


def test_step_rejects_max_turns_below_one() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        task.Step("Say hello.", max_turns=0)


def test_task_without_user_has_single_agent() -> None:
    assistant = _agent()

    single = task.Task(assistant, [_STEP])

    assert single.assistant is assistant
    assert single.user is None


def test_task_rejects_empty_steps() -> None:
    with pytest.raises(ValueError, match="step"):
        task.Task(_agent(), [])


def test_task_rejects_same_agent_in_both_roles() -> None:
    shared = _agent()

    with pytest.raises(ValueError, match="user"):
        task.Task(shared, [_STEP], user=shared)


def test_task_rejects_system_message_in_history() -> None:
    history = [message.Message("system", "Be helpful.")]

    with pytest.raises(ValueError, match="system"):
        task.Task(_agent(), [_STEP], chat_history=history)


def test_task_keeps_starting_history() -> None:
    history = [
        message.Message("user", "Hi."),
        message.Message("assistant", "Hello."),
    ]

    started = task.Task(_agent(), [_STEP], chat_history=history)

    assert started.chat_history == history


def test_tasks_do_not_share_history() -> None:
    first = task.Task(_agent(), [_STEP])
    second = task.Task(_agent(), [_STEP])

    first.chat_history.append(message.Message("user", "Hi."))

    assert second.chat_history == []
