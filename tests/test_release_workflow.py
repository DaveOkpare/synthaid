"""The deterministic release workflow through public APIs and persisted evidence."""

import json
from io import StringIO
from pathlib import Path

import pytest

from agentinstruct import (
    Inspector,
    Runner,
    TaskPackage,
    export_native,
    export_openai,
    generate_sync,
    load_run,
    load_trace,
    reverify,
)
from agentinstruct.inspection import run_terminal
from agentinstruct.traces import TraceStatus

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/release-workflow"
COUNTS: dict[TraceStatus, int] = {
    "accepted": 2,
    "rejected": 1,
    "unverified": 1,
    "invalid": 1,
    "failed": 1,
}


@pytest.fixture(autouse=True)
def component_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE))


@pytest.mark.asyncio
async def test_representative_release_run_retains_review_steps_tools_and_all_statuses(
    tmp_path: Path,
) -> None:
    package = TaskPackage.load(EXAMPLE)
    assert package.validate().valid
    result = await Runner(output_dir=tmp_path / "runs").run(
        package, seed_path=EXAMPLE / "coverage.jsonl"
    )
    assert dict(result.counts) == COUNTS
    assert [item.seed_id for item in result.traces] == [
        "ada",
        "lin",
        "rejected",
        "unverified",
        "invalid",
        "failed",
    ]
    for name, reference in zip(("Ada", "Lin"), result.traces[:2], strict=True):
        trace = load_trace(reference.path)
        assert trace.status == "accepted"
        assert [
            event.step_id for event in trace.events if event.kind == "step_started"
        ] == ["collect", "conclude"]
        assert [event.kind for event in trace.events].count("rejection") == 2
        assert [event.kind for event in trace.events].count("revision") == 2
        assert (
            trace.conversation[0].message.content
            == f"User {name}; turn=1; step=collect"
        )
        assert any(
            item.message.content == f"Conclude {name}; retained=True"
            for item in trace.conversation
        )
        assert not any("DRAFT" in item.message.content for item in trace.conversation)
        tool = next(
            item for item in trace.conversation if item.message.tool_call_id == "lookup"
        )
        assert tool.visibility == "private"
        assert json.loads(tool.message.content) == {
            "label": "safe",
            "invocation": 1,
            "seed": reference.seed_id,
        }
        assert all(
            call.id != "rejected-call"
            for item in trace.conversation
            for call in item.message.tool_calls
        )
        before = {
            path: path.read_bytes()
            for path in reference.path.iterdir()
            if path.is_file()
        }
        attempt = await reverify(reference.path, package=package)
        assert (
            attempt.status == "accepted"
            and len(load_trace(reference.path).verification) == 2
        )
        assert before == {path: path.read_bytes() for path in before}
    assert load_trace(result.traces[-1].path).conversation
    inspector = Inspector(result.path)
    assert inspector.summary()["counts"] == COUNTS
    assert "release-dialogue" in inspector.render("provenance", trace_index=0)
    output = StringIO()
    run_terminal(
        inspector, StringIO("trace 1\nconversation\ntools\nnext\nquit\n"), output
    )
    assert "Ada" in output.getvalue()
    paths = [item.path for item in result.traces]
    assert export_native(paths, tmp_path / "native.jsonl") == 2
    assert export_native(paths, tmp_path / "all.jsonl", statuses=set(COUNTS)) == 6
    assert export_openai(paths, tmp_path / "openai.jsonl") == 2
    dataset = [
        json.loads(line)
        for line in (tmp_path / "openai.jsonl").read_text().splitlines()
    ]
    call = next(
        message for message in dataset[0]["messages"] if message.get("tool_calls")
    )
    assert call["tool_calls"][0]["function"]["arguments"] == {"label": "safe"}
    assert dataset[0]["messages"][0]["role"] == "user"
    assert (
        export_openai(paths, tmp_path / "all-openai.jsonl", statuses=set(COUNTS)) == 5
    )


@pytest.mark.asyncio
async def test_run_trace_seed_export_selectors_use_current_status_and_source_order(
    tmp_path: Path,
) -> None:
    from agentinstruct import TraceSnapshot, VerificationResult

    result = await Runner(output_dir=tmp_path / "runs").run(TaskPackage.load(EXAMPLE))
    first, second = result.traces

    class Reject:
        async def verify(self, trace: TraceSnapshot) -> VerificationResult:
            return VerificationResult({"complete": False})

    await reverify(first.path, verifier_factory=lambda _: Reject())
    recorded = load_run(result.path)
    assert recorded.traces[0].recorded_status == "accepted"
    assert recorded.traces[0].snapshot.status == "rejected"
    for exporter in (export_native, export_openai):
        destination = tmp_path / f"{exporter.__name__}.jsonl"
        assert exporter([result.path], destination) == 1
        assert (
            exporter(
                [result.path],
                destination,
                run_ids={result.run_id},
                seed_ids={first.seed_id},
                statuses={"rejected"},
            )
            == 1
        )
        assert (
            exporter(
                [result.path],
                destination,
                trace_ids={first.trace_id},
                statuses={"accepted"},
            )
            == 0
        )
        assert exporter([result.path], destination, run_ids={"missing"}) == 0
    assert (
        export_native(
            [second.path, first.path],
            tmp_path / "ordered.jsonl",
            statuses={"accepted", "rejected"},
        )
        == 2
    )
    assert [
        json.loads(line)["trace_id"]
        for line in (tmp_path / "ordered.jsonl").read_text().splitlines()
    ] == [second.trace_id, first.trace_id]
    assert (
        export_native(
            [result.path],
            tmp_path / "historical.jsonl",
            verification_id=load_trace(first.path).verification[0].id,
            trace_ids={first.trace_id},
        )
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_export_protects_original_run_root_when_selection_is_empty(
    tmp_path: Path, empty: bool
) -> None:
    package = TaskPackage.load(EXAMPLE)
    result = await Runner(output_dir=tmp_path / "runs").run(
        package, seeds=[] if empty else None
    )
    before = {p: p.read_bytes() for p in result.path.rglob("*") if p.is_file()}
    for exporter in (export_native, export_openai):
        for target in (
            "manifest.json",
            "traces.jsonl",
            "source-task/task.toml",
            "new.jsonl",
        ):
            with pytest.raises(ValueError, match="overwrite source"):
                exporter([result.path], result.path / target, seed_ids={"missing"})
    assert before == {p: p.read_bytes() for p in result.path.rglob("*") if p.is_file()}


def test_sync_and_cli_release_workflows_match_the_async_lifecycle(
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    def command(*args: str, input_text: str | None = None) -> dict[str, object] | str:
        result = subprocess.run(
            ["agentinstruct", *args],
            cwd=tmp_path,
            env={
                "PATH": os.environ["PATH"],
                "PYTHONPATH": str(EXAMPLE),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stderr == ""
        return json.loads(result.stdout) if "--json" in args else result.stdout

    validation = command("validate", str(EXAMPLE), "--json")
    assert isinstance(validation, dict) and validation["status"] == "valid"
    result = generate_sync(
        TaskPackage.load(EXAMPLE), runner=Runner(output_dir=tmp_path / "sync")
    )
    cli = command("run", str(EXAMPLE), "--output", str(tmp_path / "cli"), "--json")
    assert isinstance(cli, dict) and cli["counts"] == dict(result.counts)
    assert result.counts["accepted"] == 2
    root = str(cli["path"])
    traces = load_run(root).traces
    for left, right in zip(result.traces, traces, strict=True):
        assert [
            item.message.content for item in load_trace(left.path).conversation
        ] == [item.message.content for item in right.snapshot.conversation]
    inspection = command("inspect", root, "--json")
    assert isinstance(inspection, dict) and inspection["counts"] == dict(result.counts)
    assert "ada" in command("inspect", root)
    assert "Final Ada" in command(
        "inspect", root, "--tui", input_text="trace 1\nconversation\nquit\n"
    )
    for format_name in ("native", "openai"):
        report = command(
            "export",
            root,
            "--format",
            format_name,
            "--seed-id",
            "lin",
            "--run-id",
            str(cli["run_id"]),
            "--trace-id",
            traces[1].snapshot.trace_id,
            "--output",
            str(tmp_path / f"{format_name}.jsonl"),
            "--json",
        )
        assert isinstance(report, dict) and report["count"] == 1
    path = traces[0].path
    before = {p: p.read_bytes() for p in path.iterdir() if p.is_file()}
    command("reverify", str(path), "--package", str(EXAMPLE), "--json")
    assert len(load_trace(path).verification) == 2
    assert before == {p: p.read_bytes() for p in before}
