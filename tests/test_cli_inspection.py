"""CLI and TUI read plain JSON traces without giving Episode execution behavior."""

import io
import json
from pathlib import Path

import pytest

from agentinstruct import Agent, Runner, Task
from agentinstruct.cli import main
from agentinstruct.inspection import VIEWS, Inspector, terminal_text
from agentinstruct.ui.terminal import InspectionSession, run_terminal
from tests.model_fixtures import Check, Transport, assessment, client, response

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def saved_trace(tmp_path: Path) -> Path:
    source = tmp_path / "trace.json"
    source.write_text(
        json.dumps(
            {
                "id": "recorded",
                "messages": [
                    {"role": "user", "content": "Hi"},
                    {"role": "assistant", "content": "Hello"},
                ],
                "metadata": {"input": {"name": "Ada"}},
                "verification": {"passed": True, "score": 0.75, "feedback": "Good"},
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
    offline = client(Transport(response("Hello, Ada."), assessment(True, True)))
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
    offline = client(Transport(response("Hello, Ada."), assessment(True, True)))
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
    assert inspector.view(view)
    assert inspector.render(view)
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
    assert "Unknown command" in session.execute("participant assistant")
    assert '"view": "metadata"' in session.execute("metadata")
    assert "page 2/" in session.execute("more")
    assert "page 1/" in session.execute("back")
    output = io.StringIO()
    run_terminal(
        inspector,
        io.StringIO("conversation\nverification\npage 2\nback\nquit\n"),
        output,
    )
    assert "Inspection closed" in output.getvalue()
    assert "\\u001b" in terminal_text("unsafe\x1b[31m")


def test_inspection_reads_a_trace_file_or_episode_directory(saved_trace: Path) -> None:
    for path in (saved_trace, saved_trace.parent):
        inspector = Inspector(path)
        summary = inspector.summary()
        assert not inspector.is_run and summary["kind"] == "trace"
        assert summary["messages"] == 2 and summary["status"] == "accepted"
        assert summary["path"] == str(saved_trace)
        assert summary["verification"] == {
            "passed": True,
            "score": 0.75,
            "feedback": "Good",
        }
        assert inspector.view("metadata")["metadata"] == {"input": {"name": "Ada"}}
        assert inspector.render("conversation") == "user: Hi\nassistant: Hello"


@pytest.fixture
def saved_run(tmp_path: Path, saved_trace: Path) -> Path:
    root = tmp_path / "run"
    for index, passed in enumerate((True, False, None)):
        trace = json.loads(saved_trace.read_text())
        trace["id"] = f"trace-{index}"
        trace["verification"] = (
            None if passed is None else dict(passed=passed, score=0.75, feedback="Good")
        )
        destination = root / trace["id"]
        destination.mkdir(parents=True)
        (destination / "trace.json").write_text(json.dumps(trace))
    return root


def test_run_summary_counts_saved_verdicts(saved_run: Path) -> None:
    inspector = Inspector(saved_run)
    assert inspector.is_run
    summary = inspector.view()
    assert summary == inspector.summary()
    assert summary["counts"] == {"accepted": 1, "rejected": 1, "unverified": 1}
    assert [trace["trace_id"] for trace in summary["traces"]] == [
        "trace-0",
        "trace-1",
        "trace-2",
    ]
    assert inspector.view("summary", trace_index=1)["status"] == "rejected"
    assert inspector.view("verification", trace_index=2)["verification"] is None


def test_empty_run_can_be_inspected(tmp_path: Path) -> None:
    inspector = Inspector(tmp_path)
    assert inspector.view() == {
        "kind": "run",
        "path": str(tmp_path),
        "counts": {},
        "traces": [],
    }
    session = InspectionSession(inspector)
    assert '"traces": []' in session.execute("summary")
    assert "out of range" in session.execute("next")
    assert '"kind": "run"' in session.execute("")


@pytest.mark.parametrize("view", VIEWS)
def test_cli_inspection_selects_a_trace_and_view(
    saved_run: Path, view: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(["inspect", str(saved_run), "--trace", "2", "--view", view, "--json"]) == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["trace_id"] == "trace-1"
    field = "messages" if view in {"summary", "conversation"} else view
    assert field in result


def test_tui_navigates_between_run_and_trace_summaries(saved_run: Path) -> None:
    session = InspectionSession(Inspector(saved_run), page_size=100)
    assert '"kind": "run"' in session.execute("summary")
    assert '"trace_id": "trace-0"' in session.execute("next")
    assert '"trace_id": "trace-1"' in session.execute("next")
    assert '"trace_id": "trace-0"' in session.execute("previous")
    assert '"status": "unverified"' in session.execute("trace 3")
    assert "Hi" in session.execute("conversation")
    assert '"kind": "run"' in session.execute("run")
    assert '"kind": "run"' in session.execute("summary")


@pytest.mark.parametrize("view", ["conversation", "verification", "metadata"])
def test_human_rendering_preserves_unicode_and_escapes_controls(
    saved_trace: Path, view: str
) -> None:
    trace = json.loads(saved_trace.read_text())
    text = "café\x1b[31m\u202e"
    trace["messages"][0]["content"] = text
    trace["metadata"]["note"] = text
    trace["verification"]["feedback"] = text
    saved_trace.write_text(json.dumps(trace))
    rendered = Inspector(saved_trace).render(view)
    assert "café" in rendered
    assert "\x1b" not in rendered and "\u202e" not in rendered
    assert "\\u001b" in rendered and "\\u202e" in rendered


@pytest.mark.asyncio
async def test_export_does_not_overwrite_a_trace(tmp_path: Path) -> None:
    task = Task(
        agents={"assistant": Agent("model")},
        verifier=Check(check=lambda messages: True),
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
        verifier=Check(check=lambda messages: True),
    )
    rejected = Task(
        agents={"assistant": Agent("model")},
        verifier=Check(check=lambda messages: False),
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
