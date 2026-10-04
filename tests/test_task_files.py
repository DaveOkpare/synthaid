"""Inert task authoring and execution through the conversation environment."""

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from agentinstruct import Runner
from agentinstruct.adapters.task_files import (
    SourceError,
    TaskValidationError,
    compile_records,
    load_tasks,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def package(tmp_path: Path, source: str = "verified-single") -> Path:
    root = tmp_path / "package"
    shutil.copytree(EXAMPLES / source, root)
    return root


def scripted(root: Path) -> None:
    path = root / "task.toml"
    text = path.read_text().replace(
        "[agents.assistant]",
        '[agents.assistant]\ntype = "scripted"\nresponses = ["Hello"]',
    )
    path.write_text(text)


@pytest.mark.asyncio
async def test_python_records_compile_to_the_direct_task_interface(
    tmp_path: Path,
) -> None:
    root = package(tmp_path)
    tasks = load_tasks(root, seeds=[{"name": "Ada"}, {"name": "Grace"}])
    assert len(tasks) == 2 and tasks[0].episode.id != tasks[1].episode.id
    assert all(
        task.episode.path is None and not task.episode.messages for task in tasks
    )
    episodes = await Runner(tasks, output_dir=tmp_path / "runs").run()
    assert all(
        episode.verification is not None and episode.verification.passed
        for episode in episodes
    )


def test_steps_still_compile_as_task_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLES / "stepped-dialogue"))
    tasks = load_tasks(EXAMPLES / "stepped-dialogue")
    assert len(tasks) == 1 and [segment["name"] for segment in tasks[0].segments] == [
        "collect",
        "conclude",
    ]
    assert tasks[0].episode.path is None


@pytest.mark.parametrize(
    "name",
    [
        "function-tool",
        "multi-tool",
        "stepped-dialogue",
        "custom-components",
        "release-workflow",
    ],
)
@pytest.mark.asyncio
async def test_legacy_execution_examples_require_a_custom_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLES / name))
    tasks = load_tasks(EXAMPLES / name)
    with pytest.raises(ValueError, match="UserSimEnv"):
        await Runner(tasks, output_dir=tmp_path).run()
    assert tasks[0].episode.verification is None


@pytest.mark.parametrize(
    "change", ["[agents.helper]\ntarget=false", "[agents.user]\ntarget=true"]
)
def test_unsupported_roles_and_contradictory_targets_have_explicit_migration_errors(
    tmp_path: Path, change: str
) -> None:
    root = package(tmp_path)
    path = root / "task.toml"
    path.write_text(path.read_text() + "\n" + change)
    with pytest.raises(TaskValidationError):
        list(compile_records(root))


@pytest.mark.parametrize("bad", ['{"name":"Ada",}', '{"name":NaN}', "[]", '"string"'])
def test_bad_individual_jsonl_record_does_not_hide_later_records(
    tmp_path: Path, bad: str
) -> None:
    root = package(tmp_path)
    source = tmp_path / "seeds.jsonl"
    source.write_text(bad + '\n{"name":"Grace"}\n')
    records = list(compile_records(root, seed_path=source))
    assert len(records) == 2 and records[0]["error"] and "error" not in records[1]
    assert records[0]["origin"]["record"] == 1
    assert records[1]["provenance"]["seed"]["origin"]["record"] == 2


def test_json_array_retains_valid_records_before_unreliable_source_boundary(
    tmp_path: Path,
) -> None:
    root = package(tmp_path)
    source = tmp_path / "seeds.json"
    source.write_text('[{"name":"Ada"},{"name":1}, INVALID]')
    records = compile_records(root, seed_path=source)
    assert next(records)["input"] == {"name": "Ada"}
    assert next(records)["input"] == {"name": 1}
    with pytest.raises(SourceError):
        next(records)


def test_csv_flat_keys_and_invalid_rows_keep_physical_origins(tmp_path: Path) -> None:
    root = package(tmp_path)
    path = root / "task.toml"
    path.write_text(path.read_text().replace('name = "name"', 'name = "person.name"'))
    source = tmp_path / "seeds.csv"
    source.write_text('person.name,other\nAda,x\nwrong\n"Grace\nHopper",y\n')
    records = list(compile_records(root, seed_path=source))
    assert records[0]["input"] == {"name": "Ada"}
    assert records[1]["error"] and records[1]["origin"]["record"] == 3
    assert records[2]["input"] == {"name": "Grace\nHopper"}
    assert records[2]["provenance"]["seed"]["origin"]["record"] == 4


@pytest.mark.parametrize("headers", ["a,a\n1,2\n", ",a\n1,2\n"])
def test_invalid_csv_headers_are_source_failures(tmp_path: Path, headers: str) -> None:
    root = package(tmp_path)
    source = tmp_path / "seeds.csv"
    source.write_text(headers)
    with pytest.raises(SourceError):
        list(compile_records(root, seed_path=source))


def test_seed_directory_preflights_links_before_yielding_any_record(
    tmp_path: Path,
) -> None:
    root = package(tmp_path)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "01.json").write_text('{"name":"Ada"}')
    (seeds / "99.json").symlink_to(seeds / "01.json")
    path = root / "task.toml"
    path.write_text(path.read_text().replace("[seed]", '[seed]\nglob="*"'))
    with pytest.raises(SourceError):
        next(compile_records(root, seed_path=seeds))


@pytest.mark.parametrize(
    "relative", ["../seed.json", "/tmp/seed.json", "CON", "bad\\seed.json"]
)
def test_package_paths_are_confined_and_portable(tmp_path: Path, relative: str) -> None:
    root = package(tmp_path)
    path = root / "task.toml"
    path.write_text(
        path.read_text().replace(
            'path = "seed.json"', 'path = "' + relative.replace("\\", "\\\\") + '"'
        )
    )
    with pytest.raises((TaskValidationError, OSError)):
        list(compile_records(root))


def test_instruction_symlinks_and_undeclared_layout_are_rejected(
    tmp_path: Path,
) -> None:
    root = package(tmp_path)
    instruction = root / "agents/assistant/instruction.md"
    instruction.unlink()
    instruction.symlink_to(root / "seed.json")
    with pytest.raises(TaskValidationError):
        list(compile_records(root))


@pytest.mark.parametrize(
    "text",
    ["{{ unknown }}", "{{ name.__class__ }}", "{{ name.upper }}", "{{ cycler }}"],
)
def test_templates_cannot_render_runtime_objects_or_undeclared_variables(
    tmp_path: Path, text: str
) -> None:
    root = package(tmp_path)
    (root / "agents/assistant/instruction.md").write_text(text)
    records = list(compile_records(root))
    assert records[0]["error"]


def test_compile_does_not_import_or_construct_custom_components(tmp_path: Path) -> None:
    root = package(tmp_path)
    path = root / "task.toml"
    path.write_text(
        path.read_text().replace(
            'type = "scripted"', 'type = "never_import_this:Custom"'
        )
    )
    assert list(compile_records(root))
    assert "never_import_this" not in sys.modules


@pytest.mark.parametrize(
    "name",
    [
        "verified-single",
        "scripted-single",
        "scripted-dialogue",
        "reviewed-dialogue",
        "seed-sources",
        "seed-collection",
    ],
)
@pytest.mark.asyncio
async def test_shipped_offline_packages_use_canonical_interfaces(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLES / name))
    tasks = load_tasks(EXAMPLES / name)
    episodes = await Runner(tasks, output_dir=tmp_path).run()
    assert episodes
    assert all(
        episode.path is not None and episode.path.is_file() for episode in episodes
    )


@pytest.mark.parametrize(
    "value", [{"name": object()}, {1: "Ada"}, {"name": float("nan")}]
)
def test_invalid_python_record_has_safe_evidence_without_live_values(
    tmp_path: Path, value: Any
) -> None:
    root = package(tmp_path)
    record = next(compile_records(root, seeds=[value]))
    assert record["error"] and record["origin"]["record"] == 1


@pytest.mark.parametrize(
    "change",
    [
        '[tools.bad]\nfunction="missing:capability"\nexecution_errors="ignore"',
        "[agents.assistant.model]\nmax_tokens=0",
        '[agents.assistant.model]\napi="wrong"',
    ],
)
def test_declarations_validate_locally_without_importing_components(
    change: str, tmp_path: Path
) -> None:
    root = package(tmp_path)
    path = root / "task.toml"
    path.write_text(path.read_text() + "\n" + change)
    with pytest.raises(ValueError):
        list(compile_records(root))
    assert "missing" not in sys.modules


def test_json_array_trailing_comma_is_a_source_error_after_prior_record(
    tmp_path: Path,
) -> None:
    root = package(tmp_path)
    source = tmp_path / "source.json"
    source.write_text('[{"name":"Ada"},]')
    records = iter(compile_records(root, seed_path=source))
    assert next(records)["input"]["name"] == "Ada"
    with pytest.raises(SourceError, match="Trailing comma"):
        next(records)


def test_template_iterators_cannot_render_runtime_addresses(tmp_path: Path) -> None:
    root = package(tmp_path)
    instruction = root / "agents/assistant/instruction.md"
    instruction.write_text('{{ name | list | map("upper") | string }}')
    record = next(compile_records(root, seeds=[{"name": "Ada"}]))
    assert record["agents"]["assistant"]["instruction"] == "['A', 'D', 'A']"
    assert "generator" not in record["agents"]["assistant"]["instruction"]
