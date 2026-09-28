"""Unsafe Task Packages are rejected by the public model-free compiler."""

import shutil
from pathlib import Path

import pytest

from agentinstruct import (
    Runner,
    TaskPackage,
    TaskValidationError,
    export_native,
    export_openai,
    generate_sync,
    load_trace,
)
from tests.test_collections import collection_package


@pytest.mark.parametrize("identifier", ["CON", "lpt1", "a" * 256])
@pytest.mark.parametrize("kind", ["task", "agent", "provider", "tool"])
def test_component_identifiers_share_portable_name_rules(
    tmp_path: Path, identifier: str, kind: str
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    config = package.root / "task.toml"
    text = config.read_text()
    if kind == "task":
        text = text.replace('id = "verified-greeting"', f'id = "{identifier}"')
    elif kind == "agent":
        text = text.replace("agents.assistant", f"agents.{identifier}")
    elif kind == "provider":
        text = text.replace("providers.default", f"providers.{identifier}")
    else:
        text += f'\n[tools.{identifier}]\ndescription = "Tool"\ninput_schema = true\n'
    config.write_text(text)
    with pytest.raises(TaskValidationError, match="portable"):
        TaskPackage.load(package.root)


@pytest.mark.parametrize(
    "relative", ["../outside.json", "/outside.json", "C:\\seeds.json", "NUL.json"]
)
def test_package_declared_paths_are_confined_and_portable(
    tmp_path: Path, relative: str
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace('path = "seeds.json"', f"path = '{relative}'")
    )
    with pytest.raises(TaskValidationError, match=r"seed\.path"):
        TaskPackage.load(package.root)


@pytest.mark.parametrize("kind", ["outside", "cycle", "internal"])
def test_instruction_links_are_rejected_before_compilation(
    tmp_path: Path, kind: str
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    instruction = package.root / "agents/assistant/instruction.md"
    target = (
        tmp_path / "external.md" if kind == "outside" else package.root / "template.md"
    )
    target.write_text("Hello {{ name }}")
    instruction.unlink()
    instruction.symlink_to(instruction if kind == "cycle" else target)
    with pytest.raises(TaskValidationError, match=r"instruction\.md.*symbolic links"):
        TaskPackage.load(package.root)


@pytest.mark.parametrize(
    "extra",
    ["agents/ghost", "agents/assistant/reviewer.md", "agents/assistant/rubric.toml"],
)
def test_undeclared_layout_is_rejected_with_the_specific_path(
    tmp_path: Path, extra: str
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    if "." in Path(extra).name:
        (package.root / extra).write_text("unexpected")
    else:
        (package.root / extra).mkdir()
    with pytest.raises(TaskValidationError, match=extra):
        TaskPackage.load(package.root)


def test_missing_agent_instruction_names_the_required_path(tmp_path: Path) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    (package.root / "agents/assistant/instruction.md").unlink()
    with pytest.raises(TaskValidationError, match=r"agents/assistant/instruction\.md"):
        TaskPackage.load(package.root)


def test_exact_package_path_case_is_required_on_case_insensitive_filesystems(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    (package.root / "agents/assistant/instruction.md").rename(
        package.root / "agents/assistant/Instruction.md"
    )
    with pytest.raises(TaskValidationError, match=r"instruction\.md"):
        TaskPackage.load(package.root)


@pytest.mark.parametrize("format", ["native", "openai"])
@pytest.mark.parametrize(
    "destination",
    ["snapshot", "run", "symlink", "parent-link", "hardlink", "sidecar", "standalone"],
)
def test_exports_preflight_every_source_and_preserve_immutable_evidence(
    tmp_path: Path, format: str, destination: str
) -> None:
    package = collection_package(
        tmp_path / "task", '[{"id":"a","name":"Ada"},{"id":"b","name":"Lin"}]'
    )
    result = generate_sync(package, runner=Runner(output_dir=tmp_path / "runs"))
    first, last = (item.path for item in result.traces)
    snapshot = last / "trace.json"
    original = snapshot.read_bytes()
    if destination == "snapshot":
        output = snapshot
    elif destination == "run":
        output = result.path / "dataset.jsonl"
    elif destination == "symlink":
        output = tmp_path / "linked.jsonl"
        output.symlink_to(snapshot)
    elif destination == "parent-link":
        (tmp_path / "linked").symlink_to(last, target_is_directory=True)
        output = tmp_path / "linked/dataset.jsonl"
    elif destination == "hardlink":
        output = tmp_path / "hardlinked.jsonl"
        output.hardlink_to(snapshot)
    else:
        standalone = tmp_path / "standalone.json"
        shutil.copyfile(snapshot, standalone)
        shutil.copytree(
            last / "verification", tmp_path / "standalone.json.verification"
        )
        last = standalone
        output = (
            standalone
            if destination == "standalone"
            else tmp_path / "standalone.json.verification/attempt.json"
        )
        output.parent.mkdir(exist_ok=True)
    exporter = export_native if format == "native" else export_openai
    with pytest.raises(ValueError, match=r"[Ee]xport|[Oo]utput"):
        exporter(iter([first, last]), output)
    assert snapshot.read_bytes() == original
    assert load_trace(last).status == "accepted"


def test_run_output_does_not_follow_directory_links(tmp_path: Path) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    actual = tmp_path / "actual"
    actual.mkdir()
    (tmp_path / "linked").symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match=r"[Oo]utput.*symbolic"):
        generate_sync(package, runner=Runner(output_dir=tmp_path / "linked"))
    assert list(actual.iterdir()) == []
