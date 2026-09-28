"""All Seed source forms share compilation and durable Runner outcomes."""

import json
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from agentinstruct import (
    Message,
    Observation,
    Runner,
    Seed,
    SeedOrigin,
    TaskPackage,
    TaskValidationError,
    export_native,
    export_openai,
    generate_sync,
    load_trace,
)
from agentinstruct.plans import FrozenJsonValue, JsonValue
from tests.test_collections import collection_package


class InstructionAgent:
    async def generate(self, observation: Observation) -> Message:
        return Message("assistant", observation.instruction)


@pytest.mark.asyncio
async def test_typed_json_arrays_compile_and_run_as_immutable_seed_data(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"unused","name":"unused"}')
    items: list[JsonValue] = ["first", {"labels": ["nested"]}]
    records: list[dict[str, JsonValue]] = [
        {"id": "arrays", "name": "Ada", "items": items}
    ]

    plan = package.compile(seeds=records)
    result = await Runner(output_dir=tmp_path / "runs").run(package, seeds=records)
    items.append("later caller mutation")

    assert plan.seed.data["items"] == ("first", {"labels": ("nested",)})
    assert result.traces[0].status == "accepted"
    seed = load_trace(result.traces[0].path).run_plan["seed"]
    assert isinstance(seed, Mapping)
    data = seed["data"]
    assert isinstance(data, Mapping)
    assert data["items"] == ("first", {"labels": ("nested",)})


@pytest.mark.asyncio
async def test_csv_headers_are_exact_flat_keys_and_bad_rows_keep_their_origin(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task",
        'case.id,full name\nfirst,"Ada, A."\nshort\nlong,Lin,extra\nlast,Lin\n',
        suffix="csv",
    )
    config = package.root / "task.toml"
    config.write_text(
        config.read_text()
        .replace('case_id = "id"', 'case_id = "case.id"')
        .replace('name = "name"', 'name = "full name"')
    )
    package = TaskPackage.load(package.root)
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: InstructionAgent()
    ).run(package)

    assert [item.status for item in result.traces] == [
        "accepted",
        "invalid",
        "invalid",
        "accepted",
    ]
    first = load_trace(result.traces[0].path)
    assert first.seed_id == "first"
    assert first.conversation[0].message.content == "Hello Ada, A.."
    seed_data = first.run_plan["seed"]
    assert isinstance(seed_data, Mapping)
    assert seed_data["data"] == {"case.id": "first", "full name": "Ada, A."}
    invalid = load_trace(result.traces[1].path)
    assert invalid.seed_record is not None
    assert invalid.seed_record.origin.record == 3
    assert "CSV row has 1 values; expected 2" in str(invalid.events[-1].data)
    seed = next(package.compile_records()).plan
    assert seed is not None
    assert package.compile_seed(seed.seed).variables["name"] == "Ada, A."
    native, openai = tmp_path / "native.jsonl", tmp_path / "openai.jsonl"
    assert export_native([item.path for item in result.traces], native) == 2
    assert export_openai([item.path for item in result.traces], openai) == 2
    assert json.loads(openai.read_text().splitlines()[0]) == {
        "messages": [{"role": "assistant", "content": "Hello Ada, A.."}]
    }


def test_python_iterable_preserves_explicit_seed_identity_and_indexes_bad_values(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"unused","name":"unused"}')
    cyclic: dict[str, FrozenJsonValue] = {}
    cyclic["loop"] = cyclic
    seeds: list[Seed | Mapping[str, FrozenJsonValue]] = [
        {"id": "first", "name": "Ada"},
        {"id": "not-finite", "name": float("nan")},
        cyclic,
        Seed(
            "explicit",
            {"id": "field-id", "name": "Lin"},
            SeedOrigin("memory:handwritten", 7),
            "",
        ),
    ]
    result = generate_sync(
        package, runner=Runner(output_dir=tmp_path / "runs"), seeds=iter(seeds)
    )
    assert [item.status for item in result.traces] == [
        "accepted",
        "invalid",
        "invalid",
        "accepted",
    ]
    assert [item.seed_id for item in result.traces][::3] == ["first", "explicit"]
    invalid = load_trace(result.traces[1].path)
    assert invalid.seed_record is not None
    assert invalid.seed_record.origin == SeedOrigin("python:seeds", 2, "python")
    assert "JSON-compatible" in str(invalid.events[-1].data)
    last = load_trace(result.traces[-1].path)
    seed_data = last.run_plan["seed"]
    assert isinstance(seed_data, Mapping)
    assert seed_data["origin"] == {
        "path": "memory:handwritten",
        "record": 7,
        "format": "json",
    }
    assert len(str(seed_data["digest"])) == 64
    assert package.validate(seeds=[seeds[0]]).valid
    assert package.compile(seeds=[seeds[0]]).seed.id == "first"


@pytest.mark.asyncio
async def test_iterator_failure_fails_run_after_preserving_prior_attempts(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"unused","name":"unused"}')

    def broken() -> Iterator[Mapping[str, FrozenJsonValue]]:
        yield {"id": "first", "name": "Ada"}
        raise RuntimeError("do not persist arbitrary iterator exception text")

    result = await Runner(output_dir=tmp_path / "runs").run(package, seeds=broken())
    assert result.status == "failed"
    assert result.error == "python:seeds: source iteration failed (RuntimeError)"
    assert len(result.traces) == 1
    assert load_trace(result.traces[0].path).status == "accepted"
    assert package.validate(seeds=broken()).source_error == result.error
    conflict = package.validate(seeds=[], seed_path="unneeded.json")
    assert conflict.source_error == "seeds and seed_path are mutually exclusive"


@pytest.mark.asyncio
async def test_schema_precedes_identity_and_variables_and_is_snapshotted(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task", '[{"name":"bad"},{"id":"good","name":"Ada"}]'
    )
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace("[seed]", '[seed]\nschema = "seed.schema.json"')
    )
    schema_path = package.root / "seed.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["id", "name"],
                "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
            }
        )
    )
    package = TaskPackage.load(package.root)
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert [item.status for item in result.traces] == ["invalid", "accepted"]
    invalid = load_trace(result.traces[0].path)
    assert "Seed schema violation" in str(invalid.events[-1].data)
    assert "required" in str(invalid.events[-1].data)
    assert "does not resolve" not in str(invalid.events[-1].data)
    assert (
        result.path / "source-task/seed.schema.json"
    ).read_text() == schema_path.read_text()
    schema_path.write_text('{"type":"object"}')
    changed = TaskPackage.load(package.root)
    assert changed.task.digest != package.task.digest
    # The prepared package keeps its own schema, independent of later file edits.
    assert not package.validate(seeds=[{"name": "bad"}]).valid
    direct = changed.compile(seeds=[{"id": "good", "name": "Ada"}]).seed
    with pytest.raises(TaskValidationError, match="Seed schema violation"):
        package.compile_seed(replace(direct, data={"name": "bad"}))
    invalid_explicit = package.validate(seeds=[replace(direct, data={"name": "bad"})])
    assert invalid_explicit.records[0].seed_id == "good"


def test_schema_references_cannot_request_remote_resources(tmp_path: Path) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace("[seed]", '[seed]\nschema = "schema.json"')
    )
    (package.root / "schema.json").write_text(
        '{"$ref":"https://example.invalid/schema"}'
    )
    with pytest.raises(TaskValidationError, match=r"Seed schema.*local"):
        TaskPackage.load(package.root)


@pytest.mark.asyncio
async def test_directory_orders_normalized_paths_then_records_and_requires_glob(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"unused","name":"unused"}')
    directory = package.root / "records"
    directory.mkdir()
    (directory / "b.json").write_text(
        '[{"id":"b2","name":"B2"},{"id":"b1","name":"B1"}]'
    )
    (directory / "a.json").write_text('{"id":"a","name":"A"}')
    (directory / "ignore.txt").write_text("ignored")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace('path = "seeds.json"', 'path = "records"')
    )
    package = TaskPackage.load(package.root)
    missing_glob = await Runner(output_dir=tmp_path / "missing-glob").run(package)
    assert missing_glob.status == "failed"
    assert missing_glob.traces == ()
    assert "requires seed.glob" in str(missing_glob.error)
    config.write_text(
        config.read_text().replace("[seed]", '[seed]\nglob = "**/*.json"')
    )
    package = TaskPackage.load(package.root)
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert [item.seed_id for item in result.traces] == ["a", "b2", "b1"]
    assert [item.record.origin.path for item in package.validate().records] == [
        "records/a.json",
        "records/b.json",
        "records/b.json",
    ]
    assert [item.record.origin.record for item in package.validate().records] == [
        1,
        1,
        2,
    ]
    override = await Runner(output_dir=tmp_path / "external-runs").run(
        package, seed_path=directory
    )
    assert [item.seed_id for item in override.traces] == ["a", "b2", "b1"]


@pytest.mark.asyncio
async def test_directory_preflights_later_unsafe_links_before_first_generation(
    tmp_path: Path,
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"unused","name":"unused"}')
    directory = package.root / "records"
    directory.mkdir()
    (directory / "a.json").write_text('{"id":"a","name":"A"}')
    (directory / "z.json").symlink_to(package.root / "seeds.json")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'path = "seeds.json"', 'path = "records"\nglob = "*.json"'
        )
    )
    package = TaskPackage.load(package.root)
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert result.status == "failed"
    assert result.traces == ()
    assert "symbolic links" in str(result.error)


@pytest.mark.parametrize(
    "bad", [{1: "value"}, {"value": object()}, {"value": float("inf")}]
)
def test_non_json_python_records_have_safe_stable_invalid_evidence(
    tmp_path: Path, bad: object
) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')
    result = generate_sync(
        package,
        runner=Runner(output_dir=tmp_path / "runs"),
        seeds=[cast(Mapping[str, FrozenJsonValue], bad), {"id": "good", "name": "Ada"}],
    )
    assert [item.status for item in result.traces] == ["invalid", "accepted"]
    invalid = load_trace(result.traces[0].path)
    assert invalid.seed_record is not None
    assert invalid.seed_record.origin == SeedOrigin("python:seeds", 1, "python")
    assert invalid.seed_record.raw == "<invalid Python Seed>"
    assert "object at" not in str(invalid.events)


def test_iterable_acquisition_failure_is_source_failure(tmp_path: Path) -> None:
    package = collection_package(tmp_path / "task", '{"id":"a","name":"Ada"}')

    class BrokenIterable:
        def __iter__(self) -> Iterator[Mapping[str, FrozenJsonValue]]:
            raise OSError("do not persist arbitrary exception text")

    result = generate_sync(
        package, runner=Runner(output_dir=tmp_path / "runs"), seeds=BrokenIterable()
    )
    assert result.status == "failed" and result.traces == ()
    assert result.error == "python:seeds: source iteration failed (OSError)"


@pytest.mark.parametrize(
    "source", ["id,name,name\na,Ada,Ada\n", 'id,name\na,"unfinished\n']
)
def test_csv_without_reliable_record_boundaries_fails_source(
    tmp_path: Path, source: str
) -> None:
    package = collection_package(tmp_path / "task", source, suffix="csv")
    result = generate_sync(package, runner=Runner(output_dir=tmp_path / "runs"))
    assert result.status == "failed" and result.traces == ()
    assert "CSV" in str(result.error)


def test_nested_json_selectors_and_local_schema_references_compile(
    tmp_path: Path,
) -> None:
    package = collection_package(
        tmp_path / "task", '{"id":"a","person":{"name":"Ada"}}'
    )
    config = package.root / "task.toml"
    config.write_text(
        config.read_text()
        .replace('name = "name"', 'name = "person.name"')
        .replace("[seed]", '[seed]\nschema = "schema.json"')
    )
    (package.root / "schema.json").write_text(
        json.dumps(
            {
                "type": "object",
                "$defs": {"person": {"type": "object", "required": ["name"]}},
                "properties": {
                    "person": {"$ref": "#/$defs/person"},
                    "$ref": {"type": "string"},
                },
            }
        )
    )
    package = TaskPackage.load(package.root)
    plan = package.compile()
    assert plan.agents["assistant"].base_instruction == "Hello Ada."
    forged = replace(plan.seed, digest="forged")
    assert package.compile_seed(forged).seed.digest == plan.seed.digest
    assert package.compile(seeds=[forged]).seed.digest == plan.seed.digest
    config.write_text(config.read_text().replace("person.name", "person..name"))
    report = TaskPackage.load(package.root).validate()
    assert not report.valid and "valid JSON dot path" in str(report.records[0].error)
