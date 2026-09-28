"""Read-only inspection through persisted Runs and the public navigation model."""

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentinstruct import Runner, TraceSnapshot, VerificationResult, reverify
from tests.test_collections import OutcomeAgent, OutcomeVerifier, collection_package
from tests.test_components import custom_package


class PassingVerifier:
    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        return VerificationResult({"has_reply": True, "completed": True})


class BrokenVerifier:
    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        raise RuntimeError("Latest verification failed")


@pytest.mark.asyncio
async def test_moved_run_inspection_preserves_order_and_distinguishes_current_status(
    tmp_path: Path,
) -> None:
    from agentinstruct import Inspector, load_run

    package = collection_package(
        tmp_path / "task",
        '[{"id":"invalid"},{"id":"failed","name":"failed"},'
        '{"id":"unverified","name":"unverified"},'
        '{"id":"rejected","name":"rejected"},'
        '{"id":"accepted","name":"accepted"}]',
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: OutcomeAgent(),
        verifier_factory=lambda _: OutcomeVerifier(),
    ).run(package)
    await reverify(result.traces[3].path, verifier_factory=lambda _: PassingVerifier())
    await reverify(result.traces[3].path, verifier_factory=lambda _: BrokenVerifier())
    moved = tmp_path / "moved"
    shutil.move(result.path, moved)
    shutil.rmtree(package.root)
    before = {
        p.relative_to(moved): p.read_bytes() for p in moved.rglob("*") if p.is_file()
    }
    run = load_run(moved)
    assert [item.snapshot.seed_id for item in run.traces] == [
        "invalid",
        "failed",
        "unverified",
        "rejected",
        "accepted",
    ]
    summary = json.loads(json.dumps(Inspector(moved).summary()))
    assert summary["counts"] == {
        "invalid": 1,
        "failed": 1,
        "unverified": 1,
        "rejected": 0,
        "accepted": 2,
    }
    assert summary["recorded_index_counts"] == dict.fromkeys(
        ("invalid", "failed", "unverified", "rejected", "accepted"), 1
    )
    assert summary["manifest"]["counts"]["rejected"] == 1
    changed = json.loads(json.dumps(Inspector(run.traces[3].path).summary()))
    assert changed["status"] == "accepted"
    assert changed["latest_verification"]["status"] == "unverified"
    assert changed["selected_verification"]["status"] == "accepted"
    invalid = json.loads(json.dumps(Inspector(run.traces[0].path).summary()))
    assert invalid["task"]["id"] == package.task.id
    assert invalid["seed"]["data"] == {"id": "invalid"}
    assert invalid["participants"] == []
    assert {
        p.relative_to(moved): p.read_bytes() for p in moved.rglob("*") if p.is_file()
    } == before


@pytest.mark.asyncio
async def test_operator_views_and_navigation_preserve_participant_privacy(
    tmp_path: Path,
) -> None:
    from agentinstruct import InspectionSession, Inspector

    result = await Runner(output_dir=tmp_path / "runs").run(
        custom_package(tmp_path / "task")
    )
    (result.traces[0].path / "artifacts/report.txt").write_text("Operator artifact")
    before = {
        p.relative_to(result.path): p.read_bytes()
        for p in result.path.rglob("*")
        if p.is_file()
    }
    inspector = Inspector(result.path)
    conversation = json.loads(json.dumps(inspector.view("conversation")))
    assert len(conversation["messages"]) == 5
    peer = json.loads(json.dumps(inspector.view("participant", participant="first")))
    assert len(peer["messages"]) == 3
    assert all(item["visibility"] == "shared" for item in peer["messages"])
    own = json.loads(json.dumps(inspector.view("participant", participant="target")))
    assert [item["message"]["role"] for item in own["messages"]] == [
        "user",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert len(json.loads(json.dumps(inspector.view("tools")))["messages"]) == 2
    reviews = json.dumps(inspector.view("reviews"))
    assert "rejection" in reviews and "Use safe label" in reviews
    assert "tests.component_fixtures:RoundTable" in json.dumps(
        inspector.view("provenance")
    )
    assert "accepted" in json.dumps(inspector.view("verification"))
    assert inspector.view("artifacts")["artifacts"] == [
        {"path": "report.txt", "size_bytes": 17}
    ]
    session = InspectionSession(inspector)
    assert "Run " in session.render()
    assert session.execute("summary").startswith("Run ")
    assert result.traces[0].trace_id in session.execute("next")
    session.execute("run")
    assert "Trace " in session.execute("trace 1")
    assert "Target result:" in session.execute("conversation")
    assert "private" not in session.execute("participant first")
    assert "Use safe label" in session.execute("reviews")
    assert "report.txt" in session.execute("artifacts")
    assert result.traces[1].trace_id in session.execute("next")
    assert result.traces[0].trace_id in session.execute("previous")
    assert "Unknown command" in session.execute("resume")
    assert "Unknown participant" in session.execute("participant missing")
    assert "Run " in session.execute("run")
    assert "conversation" in session.execute("help")
    session.execute("quit")
    assert session.closed
    assert {
        p.relative_to(result.path): p.read_bytes()
        for p in result.path.rglob("*")
        if p.is_file()
    } == before


@pytest.mark.asyncio
@pytest.mark.parametrize("retain", [True, False])
@pytest.mark.parametrize("outcome", ["accepted", "invalid_json", "schema_mismatch"])
async def test_reasoning_view_reads_generation_and_verification_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, retain: bool, outcome: str
) -> None:
    from agentinstruct import Inspector, ResponsesProvider, TaskPackage
    from tests.test_providers import FakeTransport
    from tests.test_responses import reasoning_item, response
    from tests.test_verification import verified_package

    root = tmp_path / "task"
    verified_package(root)
    config = root / "task.toml"
    config.write_text(
        config.read_text()
        .replace('type = "custom"', 'type = "model"')
        .replace('type = "scripted"', 'type = "model"')
        .replace('responses = ["Hello, Ada."]', "")
        .replace(
            'type = "openai"',
            f'type = "openai"\nretain_reasoning = {str(retain).lower()}',
        )
    )
    (root / "verifier/instruction.md").write_text("Judge this response.")
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    verdict = (
        '{"criteria":[{"id":"helpful","passed":true},'
        '{"id":"concise","passed":true}],"feedback":"ok"}'
    )
    if outcome == "invalid_json":
        verdict = "not JSON"
    elif outcome == "schema_mismatch":
        verdict = '{"criteria":[],"feedback":42}'
    transports = iter(
        (
            FakeTransport(
                response(
                    output=[
                        reasoning_item("agent", "agent private thought"),
                        *response("Final answer").json()["output"],
                    ]
                )
            ),
            FakeTransport(
                response(
                    output=[
                        reasoning_item("judge", "judge private thought"),
                        *response(verdict).json()["output"],
                    ]
                )
            ),
        )
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        provider_factory=lambda plan: ResponsesProvider(
            plan, transport=next(transports)
        ),
    ).run(TaskPackage.load(root))
    inspector = Inspector(result.traces[0].path)
    summary = json.loads(json.dumps(inspector.summary()))
    assert summary["latest_verification"]["status"] == (
        "accepted" if outcome == "accepted" else "unverified"
    )
    if outcome != "accepted":
        assert summary["latest_verification"]["error"]["provider_kind"] == outcome
    view = json.loads(json.dumps(inspector.view("reasoning")))
    assert [item["scope"] for item in view["calls"]] == ["generation", "verification"]
    assert all(
        item["returned"] is True and item["retained"] is retain
        for item in view["calls"]
    )
    assert all(item["retain_reasoning"] is retain for item in view["policies"])
    assert summary["reasoning"]["returned_calls"] == 2
    assert summary["reasoning"]["retained_calls"] == (2 if retain else 0)
    assert summary["reasoning"]["suppressed_calls"] == (0 if retain else 2)
    assert all(item["usage"]["total_tokens"] == 15 for item in view["calls"])
    assert all(item["request_id"] == "request-1" for item in view["calls"])
    text = inspector.render("reasoning")
    assert ("agent private thought" in text) is retain
    assert ("judge private thought" in text) is retain
    assert ("suppressed" in text) is not retain
    assert "private thought" not in inspector.render("conversation")
    assert "private thought" not in inspector.render(
        "participant", participant="assistant"
    )
    assert "private thought" not in inspector.render()
    if outcome == "accepted":
        from agentinstruct.plans import canonical_json

        # A standalone native fixture may carry both copies of one call's evidence.
        native = json.loads(canonical_json(inspector.traces[0].snapshot))
        call = next(event for event in native["events"] if "reasoning" in event["data"])
        call["data"]["error"] = {
            "kind": "schema_mismatch",
            "response": dict(call["data"]),
        }
        copied = tmp_path / "duplicated-evidence.json"
        copied.write_text(json.dumps(native))
        duplicate_view = json.loads(json.dumps(Inspector(copied).view("reasoning")))
        assert len(duplicate_view["calls"]) == 2


@pytest.mark.asyncio
async def test_step_boundaries_and_review_exhausted_messages_are_visible(
    tmp_path: Path,
) -> None:
    from agentinstruct import Inspector
    from tests.test_review import RejectingReviewer, RevisingAgent, make_review_package
    from tests.test_steps import SteppedAgent, step_package

    stepped = await Runner(
        output_dir=tmp_path / "steps", agent_factory=lambda _: SteppedAgent()
    ).run(step_package(tmp_path / "step-task"))
    inspector = Inspector(stepped.traces[0].path)
    text = inspector.render("conversation")
    assert "Task Step: collect" in text and "Task Step: conclude" in text
    assert text.index("Collected Ada.") < text.index("Task Step: conclude")
    exhausted = await Runner(
        output_dir=tmp_path / "review",
        agent_factory=RevisingAgent,
        reviewer_factory=lambda _: RejectingReviewer(),
    ).run(
        make_review_package(
            tmp_path / "review-task",
            policy="max_revisions = 0\naccept_on_revision_exhaustion = true\n",
        )
    )
    inspector = Inspector(exhausted.traces[0].path)
    assert "REVIEW EXHAUSTED" in inspector.render("conversation")
    assert "review_exhausted" in inspector.render("reviews")


def test_cli_static_json_and_terminal_navigation_are_persisted_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentinstruct import generate_sync
    from agentinstruct.cli import main
    from tests.test_import_safety import STARTUP_CHECK

    result = generate_sync(
        custom_package(tmp_path / "task"), runner=Runner(output_dir=tmp_path / "runs")
    )
    assert main(["inspect", str(result.path)]) == 0
    assert "accepted" in capsys.readouterr().out
    assert main(["inspect", str(result.path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["accepted"] == 2
    assert (
        main(
            [
                "inspect",
                str(result.path),
                "--trace",
                "2",
                "--view",
                "participant",
                "--participant",
                "first",
                "--json",
            ]
        )
        == 0
    )
    projection = json.loads(capsys.readouterr().out)
    assert projection["trace_id"] == result.traces[1].trace_id
    assert len(projection["messages"]) == 3
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "trace 1\nconversation\nparticipant first\nverification\nnext\nquit\n"
        ),
    )
    assert main(["inspect", str(result.path), "--tui"]) == 0
    output = capsys.readouterr().out
    assert "Commands:" in output and "Inspection closed" in output
    assert "Target result:" in output and result.traces[1].trace_id in output
    for arguments in (
        ["--trace", "99"],
        ["--view", "participant", "--participant", "missing"],
    ):
        assert main(["inspect", str(result.path), *arguments, "--json"]) == 1
        assert json.loads(capsys.readouterr().out)["status"] == "error"
    checked = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            STARTUP_CHECK,
            "inspect",
            str(result.path),
            "--json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["counts"]["accepted"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "damage",
    [
        "escape",
        "absolute",
        "directory_link",
        "snapshot_link",
        "sidecar_link",
        "run_id",
        "trace_id",
        "seed_id",
        "duplicate",
    ],
)
async def test_run_discovery_rejects_unconfined_or_mismatched_index_entries(
    tmp_path: Path, damage: str
) -> None:
    from agentinstruct import load_run

    result = await Runner(output_dir=tmp_path / "runs").run(
        collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    )
    index = result.path / "traces.jsonl"
    entry = json.loads(index.read_text())
    source = result.traces[0].path
    outside = tmp_path / "outside"
    shutil.copytree(source, outside)
    if damage == "escape":
        entry["path"] = "../../outside"
    elif damage == "absolute":
        entry["path"] = str(outside)
    elif damage == "directory_link":
        shutil.rmtree(source)
        source.symlink_to(outside, target_is_directory=True)
    elif damage == "snapshot_link":
        (source / "trace.json").unlink()
        (source / "trace.json").symlink_to(outside / "trace.json")
    elif damage == "sidecar_link":
        shutil.rmtree(source / "verification")
        (source / "verification").symlink_to(
            outside / "verification", target_is_directory=True
        )
    elif damage == "run_id":
        manifest = result.path / "manifest.json"
        content = json.loads(manifest.read_text())
        content["run_id"] = "different-run"
        manifest.write_text(json.dumps(content))
    elif damage in {"trace_id", "seed_id"}:
        entry[damage] = "wrong-id"
    index.write_text(json.dumps(entry) + "\n")
    if damage == "duplicate":
        index.write_text(index.read_text() * 2)
    with pytest.raises(ValueError, match=r"confined|escapes|identity|duplicate"):
        load_run(result.path)


@pytest.mark.asyncio
async def test_empty_runs_standalone_snapshots_pagination_and_safe_terminal_text(
    tmp_path: Path,
) -> None:
    from agentinstruct import InspectionSession, Inspector

    empty = await Runner(output_dir=tmp_path / "empty").run(
        collection_package(tmp_path / "empty-task", "[]")
    )
    inspector = Inspector(empty.path)
    assert inspector.summary()["counts"] == dict.fromkeys(
        ("invalid", "failed", "unverified", "rejected", "accepted"), 0
    )
    session = InspectionSession(inspector)
    assert "out of range" in session.execute("trace 1")
    assert "Run " in session.render()
    assert session.execute("summary").startswith("Run ")
    failed = await Runner(output_dir=tmp_path / "failed").run(
        collection_package(tmp_path / "failed-task", "[")
    )
    assert failed.error is not None
    assert failed.error in Inspector(failed.path).render()
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: OutcomeAgent()
    ).run(
        collection_package(
            tmp_path / "task", json.dumps({"id": "a", "name": "\u001b[2J\u202edanger"})
        )
    )
    snapshot = tmp_path / "snapshot.json"
    shutil.copyfile(result.traces[0].path / "trace.json", snapshot)
    inspector = Inspector(snapshot)
    assert inspector.view("artifacts")["artifacts"] == []
    text = inspector.render("conversation")
    assert "\u001b" not in text and "\u202e" not in text
    assert "\\x1b" in text and "\\u202e" in text
    session = InspectionSession(inspector, page_size=2)
    assert "page 1/" in session.execute("conversation")
    assert "page 2/" in session.execute("more")
    assert "page 1/" in session.execute("back")
    assert "page 1/" in session.execute("page 1")
