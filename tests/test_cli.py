"""Smoke tests at the installed console-command boundary."""

import json
import os
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "single-agent"


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["agentinstruct", *args],
        cwd=cwd,
        env={
            **{
                key: os.environ[key]
                for key in ("PATH", "SYSTEMROOT")
                if key in os.environ
            },
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_installed_command_reports_distribution_version(tmp_path: Path) -> None:
    result = run_command(["--version"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"agentinstruct {version('agentinstruct')}\n"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_installed_command_rejects_unknown_arguments(tmp_path: Path) -> None:
    result = run_command(["--unknown-option"], tmp_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert "unrecognized arguments: --unknown-option" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("args", [[], ["--help"], ["-h"]])
def test_installed_command_shows_help(args: list[str], tmp_path: Path) -> None:
    result = run_command(args, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "usage: agentinstruct" in result.stdout
    assert "--help" in result.stdout
    assert "--version" in result.stdout
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_validate_reports_success_as_json(tmp_path: Path) -> None:
    result = run_command(["validate", str(EXAMPLE), "--json"], tmp_path)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "valid"
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_validate_forwards_seed_override(tmp_path: Path) -> None:
    seed_path = tmp_path / "other.json"
    seed_path.write_text(
        '{"case":{"id":"other"},"person":{"name":"Lin"},"scenario":{"topic":"music"}}',
        encoding="utf-8",
    )

    result = run_command(
        ["validate", str(EXAMPLE), "--seed", "other.json", "--json"], tmp_path
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["plan"]["seed"]["id"] == "other"
    assert result.stderr == ""


@pytest.mark.parametrize("as_json", [False, True])
def test_validate_reports_precise_failure(tmp_path: Path, as_json: bool) -> None:
    seed_path = tmp_path / "broken.json"
    seed_path.write_text("{", encoding="utf-8")
    args = ["validate", str(EXAMPLE), "--seed", str(seed_path)]
    if as_json:
        args.append("--json")

    result = run_command(args, tmp_path)

    assert result.returncode == 2
    if as_json:
        output = json.loads(result.stdout)
        assert output["status"] == "invalid"
        assert "malformed JSON at line 1, column 2" in output["error"]
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert "Validation failed:" in result.stderr
        assert "malformed JSON at line 1, column 2" in result.stderr


def test_validate_reports_nonfinite_json_as_validation_failure(tmp_path: Path) -> None:
    seed_path = tmp_path / "broken.json"
    seed_path.write_text('{"value": NaN}', encoding="utf-8")

    result = run_command(
        ["validate", str(EXAMPLE), "--seed", str(seed_path), "--json"], tmp_path
    )

    assert result.returncode == 2
    output = json.loads(result.stdout)
    assert output["status"] == "invalid"
    assert "non-finite" in output["error"]
    assert result.stderr == ""


@pytest.mark.parametrize("as_json", [False, True])
def test_run_generates_scripted_trace_and_forwards_overrides(
    tmp_path: Path, as_json: bool
) -> None:
    package = tmp_path / "task"
    shutil.copytree(EXAMPLE, package)
    with (package / "task.toml").open("a") as config:
        config.write('\ntype = "scripted"\nresponses = ["Hello from the script."]\n')
    (tmp_path / "override.json").write_text(
        '{"case":{"id":"cli-seed"},"person":{"name":"Lin"},'
        '"scenario":{"topic":"music"}}'
    )
    args = ["run", str(package), "--seed", "override.json", "--output", "results"]
    if as_json:
        args.append("--json")

    result = run_command(args, tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    if as_json:
        report = json.loads(result.stdout)
        assert report["counts"]["unverified"] == 1
        trace_path = Path(report["traces"][0]["path"]) / "trace.json"
    else:
        assert "unverified=1" in result.stdout
        trace_path = next((tmp_path / "results").glob("*/traces/*/trace.json"))
    trace = json.loads(trace_path.read_text())
    assert trace["seed_id"] == "cli-seed"
    assert trace["conversation"][0]["message"]["content"] == "Hello from the script."


def test_run_reports_failed_trace_for_missing_model_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "missing-credentials"
    shutil.copytree(EXAMPLE, package)
    config = package / "task.toml"
    config.write_text(
        config.read_text().replace(
            'api_key_env = "OPENAI_API_KEY"',
            'api_key_env = "AGENTINSTRUCT_MISSING_TEST_KEY"',
        )
    )
    monkeypatch.delenv("AGENTINSTRUCT_MISSING_TEST_KEY", raising=False)
    result = run_command(["run", str(package), "--json"], tmp_path)

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["counts"]["failed"] == 1
    trace = json.loads((Path(report["traces"][0]["path"]) / "trace.json").read_text())
    assert trace["status"] == "failed"
    assert trace["conversation"] == []
    assert any(event["kind"] == "error" for event in trace["events"])


def test_run_records_source_failure_without_inventing_a_trace(tmp_path: Path) -> None:
    (tmp_path / "bad.json").write_text("{")

    result = run_command(
        ["run", str(EXAMPLE), "--seed", "bad.json", "--json"], tmp_path
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["status"] == "failed"
    assert "malformed JSON" in report["error"]
    assert report["traces"] == []
    manifest = json.loads((Path(report["path"]) / "manifest.json").read_text())
    assert manifest["status"] == "failed"


@pytest.mark.parametrize("fail_fast, count", [(False, 2), (True, 1)])
def test_collection_run_forwards_fail_fast(
    tmp_path: Path, fail_fast: bool, count: int
) -> None:
    source = tmp_path / "collection.jsonl"
    source.write_text('{broken\n{"name":"Ada"}\n')
    args = [
        "run",
        str(EXAMPLE.parent / "verified-single"),
        "--seed",
        str(source),
        "--json",
    ]
    result = run_command([*args, *(["--fail-fast"] if fail_fast else [])], tmp_path)
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert len(report["traces"]) == count
    assert report["counts"]["invalid"] == 1


def test_validate_reports_every_collection_record_without_run_storage(
    tmp_path: Path,
) -> None:
    source = tmp_path / "collection.jsonl"
    source.write_text('\n{"name":"Ada"}\n{broken\n{"name":"Lin"}\n')
    result = run_command(
        [
            "validate",
            str(EXAMPLE.parent / "verified-single"),
            "--seed",
            str(source),
            "--json",
        ],
        tmp_path,
    )
    assert result.returncode == 2
    report = json.loads(result.stdout)
    assert report["status"] == "invalid"
    assert report["counts"] == {"valid": 2, "invalid": 1}
    assert [record["origin"]["record"] for record in report["records"]] == [2, 3, 4]
    assert "column 2" in report["records"][1]["error"]
    assert len(report["plans"]) == 2
    assert not (tmp_path / "runs").exists()


def test_validate_compiles_an_entire_valid_collection(tmp_path: Path) -> None:
    source = tmp_path / "collection.json"
    source.write_text('[{"name":"Ada"},{"name":"Lin"}]')
    result = run_command(
        [
            "validate",
            str(EXAMPLE.parent / "verified-single"),
            "--seed",
            str(source),
            "--json",
        ],
        tmp_path,
    )
    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["status"] == "valid"
    assert report["counts"] == {"valid": 2, "invalid": 0}
    assert len(report["plans"]) == 2
    assert "plan" not in report
    assert not (tmp_path / "runs").exists()


def test_csv_override_and_directory_source_share_cli_compilation(
    tmp_path: Path,
) -> None:
    example = EXAMPLE.parent / "seed-sources"
    report = run_command(["validate", str(example), "--json"], tmp_path)
    assert report.returncode == 0, report.stderr
    assert [item["seed_id"] for item in json.loads(report.stdout)["records"]] == [
        "csv-a",
        "csv-b",
        "json-c",
    ]
    source = tmp_path / "override.csv"
    source.write_text("id,name\noverride,Ada\n")
    result = run_command(
        ["run", str(example), "--seed", str(source), "--json"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["traces"][0]["seed_id"] == "override"


@pytest.mark.parametrize("export_format", ["native", "openai"])
def test_export_forwards_format_and_explicit_status_selection(
    tmp_path: Path, export_format: str
) -> None:
    result = run_command(
        ["run", str(EXAMPLE.parent / "scripted-single"), "--json"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    trace = json.loads(result.stdout)["traces"][0]["path"]
    args = [
        "export",
        trace,
        "--format",
        export_format,
        "--output",
        "dataset.jsonl",
        "--json",
    ]

    excluded = run_command(args, tmp_path)
    assert excluded.returncode == 0, excluded.stderr
    assert json.loads(excluded.stdout)["count"] == 0
    assert (tmp_path / "dataset.jsonl").read_text() == ""

    included = run_command([*args, "--status", "unverified"], tmp_path)
    assert included.returncode == 0, included.stderr
    assert json.loads(included.stdout)["count"] == 1
    row = json.loads((tmp_path / "dataset.jsonl").read_text())
    if export_format == "native":
        assert row["status"] == "unverified"
    else:
        assert row == {"messages": [{"role": "assistant", "content": "Hello, Ada."}]}


def test_reverify_forwards_package_override_and_export_attempt_selection(
    tmp_path: Path,
) -> None:
    package = tmp_path / "task"
    shutil.copytree(EXAMPLE.parent / "scripted-single", package)
    with (package / "task.toml").open("a") as config:
        config.write(
            '\n[verifier]\ntype = "deterministic"\n'
            '[verifier.checks]\nreply = "nonempty_conversation"\n'
        )
    (package / "verifier").mkdir()
    rubric = package / "verifier" / "rubric.toml"
    rubric.write_text('threshold = 1.0\n[[criteria]]\nid = "reply"\nweight = 1.0\n')
    generated = run_command(["run", str(package), "--json"], tmp_path)
    assert generated.returncode == 0, generated.stderr
    trace = Path(json.loads(generated.stdout)["traces"][0]["path"])
    conversation = (trace / "conversation.jsonl").read_bytes()
    rubric.write_text(rubric.read_text().replace("1.0", "0.5", 1))

    result = run_command(
        ["reverify", str(trace), "--package", str(package), "--json"], tmp_path
    )

    assert result.returncode == 0, result.stderr
    attempt = json.loads(result.stdout)["attempts"][0]
    assert attempt["sequence"] == 2
    assert attempt["status"] == "accepted"
    assert attempt["plan"]["rubric"]["threshold"] == 0.5
    assert (trace / "conversation.jsonl").read_bytes() == conversation
    exported = run_command(
        [
            "export",
            str(trace),
            "--verification",
            attempt["id"],
            "--output",
            "dataset.jsonl",
            "--json",
        ],
        tmp_path,
    )
    assert exported.returncode == 0, exported.stderr
    assert json.loads(exported.stdout)["count"] == 1
    default_policy = run_command(["reverify", str(trace)], tmp_path)
    assert default_policy.returncode == 0, default_policy.stderr
    assert "accepted (score=1.0)" in default_policy.stdout


def test_reverify_reports_missing_verifier_policy(tmp_path: Path) -> None:
    generated = run_command(
        ["run", str(EXAMPLE.parent / "scripted-single"), "--json"], tmp_path
    )
    trace = json.loads(generated.stdout)["traces"][0]["path"]

    result = run_command(["reverify", trace, "--json"], tmp_path)

    assert result.returncode == 1
    assert json.loads(result.stdout)["status"] == "error"
    assert "no Verifier Plan" in json.loads(result.stdout)["error"]
