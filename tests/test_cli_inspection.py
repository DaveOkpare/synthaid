"""CLI and TUI read plain JSON traces without giving Episode execution behavior."""

import io
import json
from pathlib import Path

import pytest

from agentinstruct import Agent, Judge, Runner, Task
from agentinstruct.cli import main
from agentinstruct.inspection import VIEWS, Inspector, terminal_text
from agentinstruct.ui.terminal import InspectionSession, run_terminal
from tests.model_fixtures import Transport, client, response

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def saved_trace(tmp_path: Path) -> Path:
    source = tmp_path / "trace.json"
    source.write_text(
        json.dumps(
            {
                "id": "recorded",
                "messages": [{"role": "assistant", "content": "Hello"}],
                "metadata": {},
                "verification": {"passed": True},
            }
        )
    )
    return source


def test_cli_help_and_validation_are_inert(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    assert main(["validate", str(EXAMPLES / "verified-single"), "--json"]) == 0
    report = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert report["status"] == "valid" and report["counts"]["valid"] == 1
    assert not list(tmp_path.iterdir())


def test_cli_run_inspect_and_export_read_saved_trace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    offline = client(Transport(response("Hello, Ada.")))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: offline)
    output = tmp_path / "runs"
    assert (
        main(
            [
                "run",
                str(EXAMPLES / "verified-single"),
                "--output",
                str(output),
                "--json",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["counts"] == {"accepted": 1}
    inspector = Inspector(output)
    assert len(inspector.traces) == 1
    source = inspector.paths[0]
    before = source.read_bytes()
    assert main(["inspect", str(output), "--json"]) == 0
    capsys.readouterr()
    dataset = tmp_path / "training.jsonl"
    assert main(["export", str(output), "--output", str(dataset), "--json"]) == 0
    assert json.loads(dataset.read_text()) == {
        "messages": [{"role": "assistant", "content": "Hello, Ada."}]
    }
    assert source.read_bytes() == before


def test_invalid_records_remain_in_report_without_fabricating_episodes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    offline = client(Transport(response("Hello, Ada.")))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kwargs: offline)
    source = tmp_path / "inputs.jsonl"
    source.write_text('not json\n{"name":"Ada"}\n')
    output = tmp_path / "runs"
    assert (
        main(
            [
                "run",
                str(EXAMPLES / "verified-single"),
                "--seed",
                str(source),
                "--output",
                str(output),
                "--json",
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["counts"] == {"invalid": 1, "accepted": 1}
    assert report["traces"][0]["error"]
    assert len(Inspector(output).traces) == 1


@pytest.mark.parametrize("view", VIEWS)
def test_recorded_views_only_read_the_snapshot(view: str, saved_trace: Path) -> None:
    before = saved_trace.read_bytes()
    inspector = Inspector(saved_trace)
    participant = "assistant" if view == "participant" else None
    assert inspector.view(view, participant=participant)
    assert inspector.render(view, participant=participant)
    assert saved_trace.read_bytes() == before


def test_old_trace_format_is_explicitly_unsupported() -> None:
    source = Path(__file__).parent / "fixtures/compatibility/v0.1.0-reviewed-trace"
    with pytest.raises(ValueError, match="Unsupported trace format"):
        Inspector(source)


def test_tui_navigation_is_read_only(saved_trace: Path) -> None:
    inspector = Inspector(saved_trace)
    session = InspectionSession(inspector, page_size=2)
    assert "Unknown" in session.execute("unsupported")
    assert "page" in session.execute("conversation")
    assert "Unknown participant" in session.execute("participant missing")
    output = io.StringIO()
    run_terminal(
        inspector,
        io.StringIO("conversation\nverification\npage 2\nback\nquit\n"),
        output,
    )
    assert "Inspection closed" in output.getvalue()
    assert "\\u001b" in terminal_text("unsafe\x1b[31m")


@pytest.mark.asyncio
async def test_export_does_not_overwrite_a_trace(tmp_path: Path) -> None:
    task = Task(
        agents={"assistant": Agent("model")},
        verifier=Judge(check=lambda messages: True),
    )
    async with client(Transport(response())) as borrowed:
        await Runner([task], output_dir=tmp_path, client=borrowed).run()
    assert task.episode.path is not None
    source = task.episode.path
    before = source.read_bytes()
    assert main(["export", str(source), "--output", str(source)]) == 1
    assert source.read_bytes() == before


@pytest.mark.asyncio
async def test_export_filters_verdicts_and_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    accepted = Task(
        agents={"assistant": Agent("model")},
        verifier=Judge(check=lambda messages: True),
    )
    rejected = Task(
        agents={"assistant": Agent("model")},
        verifier=Judge(check=lambda messages: False),
    )
    async with client(Transport(response(), response())) as borrowed:
        await Runner(
            [accepted, rejected], output_dir=tmp_path / "runs", client=borrowed
        ).run()
    output = tmp_path / "selected.jsonl"
    assert (
        main(
            [
                "export",
                str(tmp_path / "runs"),
                "--status",
                "rejected",
                "--trace-id",
                rejected.episode.id,
                "--format",
                "native",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    trace = json.loads(output.read_text())
    assert trace["id"] == rejected.episode.id and not trace["verification"]["passed"]
    capsys.readouterr()
