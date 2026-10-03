"""CLI and TUI consume recorded Episodes without re-entering execution."""

import io
import json
from pathlib import Path

import pytest

from agentinstruct import Judge, Runner, Task
from agentinstruct.cli import main
from agentinstruct.inspection import VIEWS, Inspector, terminal_text
from agentinstruct.ui.terminal import InspectionSession, run_terminal
from tests.test_generation import Reply

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
HISTORICAL = Path(__file__).parent / "fixtures/compatibility/v0.1.0-reviewed-trace"


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


def test_cli_run_inspect_export_and_reverify_share_the_same_episode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    source = inspector.traces[0].path
    assert source is not None
    before = (source / "trace.json").read_bytes()
    assert main(["inspect", str(output), "--json"]) == 0
    capsys.readouterr()
    assert (
        main(
            [
                "reverify",
                str(source),
                "--package",
                str(EXAMPLES / "verified-single"),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert len(Inspector(source).traces[0].verification) == 2
    assert (source / "trace.json").read_bytes() == before
    dataset = tmp_path / "training.jsonl"
    assert main(["export", str(output), "--output", str(dataset), "--json"]) == 0
    assert json.loads(dataset.read_text()) == {
        "messages": [{"role": "assistant", "content": "Hello, Ada."}]
    }


def test_invalid_records_and_source_failures_remain_distinct(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    assert len(Inspector(output).traces) == 2


@pytest.mark.parametrize("view", VIEWS)
def test_historical_recorded_views_are_readable_without_runtime(view: str) -> None:
    inspector = Inspector(HISTORICAL)
    participant = (
        inspector.traces[0].messages[0].actor_id if view == "participant" else None
    )
    assert inspector.view(view, participant=participant)
    assert inspector.render(view, participant=participant)


def test_tui_custom_stream_navigation_and_errors_are_read_only() -> None:
    inspector = Inspector(HISTORICAL)
    session = InspectionSession(inspector, page_size=2)
    assert "Unknown" in session.execute("unsupported")
    assert "page" in session.execute("conversation")
    assert "Unknown participant" in session.execute("participant missing")
    output = io.StringIO()
    run_terminal(
        inspector, io.StringIO("conversation\nreasoning\npage 2\nback\nquit\n"), output
    )
    assert "Inspection closed" in output.getvalue()
    assert "\\u001b" in terminal_text("unsafe\x1b[31m")


@pytest.mark.asyncio
async def test_inspection_and_export_exclude_rejected_drafts_from_participant_view(
    tmp_path: Path,
) -> None:
    task = Task(
        agents={"assistant": Reply()}, verifier=Judge(check=lambda messages: True)
    )
    await Runner([task], output_dir=tmp_path).run()
    assert task.episode.path is not None
    inspector = Inspector(task.episode.path)
    assert (
        inspector.view("participant", participant="assistant")["messages"][0]["content"]
        == "Hello"
    )
    before = (task.episode.path / "trace.json").read_bytes()
    assert (
        main(
            [
                "export",
                str(task.episode.path),
                "--output",
                str(task.episode.path / "trace.json"),
            ]
        )
        == 2
    )
    assert (task.episode.path / "trace.json").read_bytes() == before


def test_run_discovery_rejects_escape_and_duplicate_index_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "manifest.json").write_text(json.dumps({"run_id": "recorded"}))
    (tmp_path / "traces.jsonl").write_text(
        json.dumps({"path": "../trace.json", "trace_id": "x"})
    )
    with pytest.raises(ValueError):
        Inspector(tmp_path)


@pytest.mark.asyncio
async def test_export_selects_an_immutable_verification_attempt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    task = Task(
        agents={"assistant": Reply()}, verifier=Judge(check=lambda messages: True)
    )
    await Runner([task], output_dir=tmp_path / "runs").run()
    accepted = task.episode.verification[0]["id"]
    await task.episode.verify(Judge(check=lambda messages: False))
    destination = tmp_path / "selected.jsonl"
    assert (
        main(
            [
                "export",
                str(task.episode.path),
                "--verification",
                accepted,
                "--format",
                "native",
                "--output",
                str(destination),
            ]
        )
        == 0
    )
    data = json.loads(destination.read_text())
    assert data["status"] == "accepted" and data["selected_verification_id"] == accepted
    assert task.episode.status == "rejected"
    missing = tmp_path / "missing.jsonl"
    assert (
        main(
            [
                "export",
                str(task.episode.path),
                "--verification",
                "missing",
                "--output",
                str(missing),
            ]
        )
        == 2
    )
    assert not missing.exists()
    capsys.readouterr()
