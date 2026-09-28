"""Explicit component references through the Runner and durable public artifacts."""

import json
from pathlib import Path

import pytest

from agentinstruct import Runner, TaskPackage, export_openai, load_trace, reverify


def custom_package(root: Path) -> TaskPackage:
    root.mkdir()
    (root / "task.toml").write_text("""schema_version = "1"
[task]
id = "custom-round-table"
version = "1"
[seed]
path = "seed.json"
[providers.default]
type = "openai"
[model]
provider = "default"
name = "unused"
[runtime]
type = "local"
[environment]
type = "tests.component_fixtures:RoundTable"
[agents.first]
type = "tests.component_fixtures:Participant"
target = false
[agents.second]
type = "tests.component_fixtures:Participant"
target = false
[agents.target]
type = "tests.component_fixtures:Participant"
target = true
tools = ["lookup"]
[agents.target.reviewer]
type = "tests.component_fixtures:Reviewer"
[tools.lookup]
type = "tests.component_fixtures:Lookup"
description = "Return a safe label"
[tools.lookup.input_schema]
type = "object"
properties = {label = {type = "string"}}
required = ["label"]
additionalProperties = false
[verifier]
type = "tests.component_fixtures:Verifier"
""")
    (root / "seed.json").write_text('[{"id":1},{"id":2}]')
    for actor in ("first", "second", "target"):
        directory = root / "agents" / actor
        directory.mkdir(parents=True)
        (directory / "instruction.md").write_text("Join the discussion.")
    (root / "agents/target/reviewer.md").write_text("Require the safe label.")
    (root / "agents/target/rubric.toml").write_text('[[criteria]]\nid="safe"\n')
    (root / "verifier").mkdir()
    (root / "verifier/rubric.toml").write_text('[[criteria]]\nid="complete"\n')
    return TaskPackage.load(root)


@pytest.mark.asyncio
async def test_explicit_components_run_fresh_reviewed_verified_multi_party_traces(
    tmp_path: Path,
) -> None:
    package = custom_package(tmp_path / "task")
    assert package.validate().valid
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert result.counts["accepted"] == 2
    for reference in result.traces:
        trace = load_trace(reference.path)
        assert trace.generation.reason == "round_table_complete"
        assert [item.message.content for item in trace.conversation[:2]] == [
            "first:1:seen=0",
            "second:1:seen=1",
        ]
        assert trace.conversation[2].message.tool_calls[0].function.arguments == {
            "label": "safe"
        }
        assert [item.visibility for item in trace.conversation] == [
            "shared",
            "shared",
            "private",
            "private",
            "shared",
        ]
        assert any(event.kind == "rejection" for event in trace.events)
        assert trace.verification[0].score == 1.0
        assert all(item.digest for item in trace.components)
        assert not any(item.kind.startswith("provider:") for item in trace.components)
    path = result.traces[0].path
    generation = (path / "conversation.jsonl").read_bytes()
    assert (await reverify(path)).status == "accepted"
    assert (path / "conversation.jsonl").read_bytes() == generation
    output = tmp_path / "dataset.jsonl"
    assert export_openai([path], output) == 1
    messages = json.loads(output.read_text())["messages"]
    assert [message["role"] for message in messages] == [
        "user",
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("finalizer", ["StaticMethod", "ClassMethod"])
async def test_explicit_static_and_class_methods_validate_and_run(
    tmp_path: Path, finalizer: str
) -> None:
    root = tmp_path / "task"
    custom_package(root)
    task = root / "task.toml"
    task.write_text(
        task.read_text()
        .replace(
            "tests.component_fixtures:Participant",
            "tests.component_fixtures:ClassMethodParticipant",
            1,
        )
        .replace(
            "tests.component_fixtures:Lookup",
            "tests.component_fixtures:StaticMethodLookup",
        )
        .replace(
            "tests.component_fixtures:RoundTable",
            f"tests.component_fixtures:{finalizer}FinalizingRoundTable",
        )
    )
    package = TaskPackage.load(root)
    assert package.validate().valid
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    assert result.counts["accepted"] == 2
    for reference in result.traces:
        trace = load_trace(reference.path)
        assert trace.conversation[0].message.content == "ClassMethodParticipant:first"
        assert json.loads(trace.conversation[3].message.content) == {
            "label": "safe",
            "actor": "target",
        }
        assert any(event.kind == "environment_finalize" for event in trace.events)


@pytest.mark.parametrize(
    ("before", "reference", "expected"),
    [
        (
            "tests.component_fixtures:Participant",
            "missing.module:scripted",
            "lookup failed",
        ),
        (
            "tests.component_fixtures:Participant",
            "tests.component_fixtures:missing",
            "lookup failed",
        ),
        (
            "tests.component_fixtures:Participant",
            "tests.component_fixtures:MissingAgent",
            "requires async generate",
        ),
        (
            "tests.component_fixtures:Participant",
            "tests.component_fixtures:WrongSignatureAgent",
            "generate must accept",
        ),
        (
            "tests.component_fixtures:RoundTable",
            "tests.component_fixtures:WrongEnvironment",
            "constructor must accept 0",
        ),
        (
            "tests.component_fixtures:Reviewer",
            "tests.component_fixtures:WrongReviewer",
            "requires async review",
        ),
        (
            "tests.component_fixtures:Verifier",
            "tests.component_fixtures:MissingAgent",
            "requires async verify",
        ),
        (
            "tests.component_fixtures:Lookup",
            "tests.component_fixtures:MissingAgent",
            "requires async call",
        ),
    ],
)
def test_explicit_reference_failure_names_the_reference_without_fallback(
    tmp_path: Path,
    before: str,
    reference: str,
    expected: str,
) -> None:
    from agentinstruct import TaskValidationError

    root = tmp_path / "task"
    custom_package(root)
    task = root / "task.toml"
    task.write_text(task.read_text().replace(before, reference))
    with pytest.raises(TaskValidationError) as error:
        TaskPackage.load(root)
    assert reference in str(error.value) and expected in str(error.value)


@pytest.mark.asyncio
async def test_validation_does_not_construct_custom_components(tmp_path: Path) -> None:
    root = tmp_path / "task"
    custom_package(root)
    task = root / "task.toml"
    reference = "tests.component_fixtures:ConstructorGuard"
    task.write_text(
        task.read_text().replace("tests.component_fixtures:Participant", reference)
    )
    package = TaskPackage.load(root)
    assert package.validate().valid
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and not trace.conversation
    errors = [event for event in trace.events if event.kind == "error"]
    assert reference in str(errors)


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["function", "agent"])
async def test_explicit_tool_adapters_preserve_configuration_and_review(
    tmp_path: Path, adapter: str
) -> None:
    root = tmp_path / "task"
    custom_package(root)
    task = root / "task.toml"
    settings = (
        'type = "function"\nfunction = "tests.component_fixtures:lookup_function"'
    )
    if adapter == "agent":
        settings = '''type = "agent"
agent_factory = "tests.component_fixtures:Subordinate"
agent_config = {label = "safe"}
instruction = "Return your configured label as JSON."'''
    task.write_text(
        task.read_text().replace('type = "tests.component_fixtures:Lookup"', settings)
    )
    result = await Runner(output_dir=tmp_path / "runs").run(TaskPackage.load(root))
    assert result.counts["accepted"] == 2
    for reference in result.traces:
        trace = load_trace(reference.path)
        output = json.loads(trace.conversation[3].message.content)
        assert output["label"] == "safe"
        component = next(
            item for item in trace.components if item.kind == "tool:lookup"
        )
        assert component.reference == "tests.component_fixtures:" + (
            "lookup_function" if adapter == "function" else "Subordinate"
        )
        if adapter == "agent":
            assert output["calls"] == 1
            assert output["instruction"] == "Return your configured label as JSON."
            assert component.configuration == {
                "instruction": "Return your configured label as JSON.",
                "agent_config": {"label": "safe"},
            }


@pytest.mark.asyncio
async def test_runtime_tool_protocol_failure_precedes_any_generation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "task"
    custom_package(root)
    task = root / "task.toml"
    reference = "tests.component_fixtures:MissingTool"
    task.write_text(
        task.read_text().replace("tests.component_fixtures:Lookup", reference)
    )
    package = TaskPackage.load(root)
    result = await Runner(output_dir=tmp_path / "runs").run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed" and not trace.conversation
    assert reference in str(trace.events) and "requires id" in str(trace.events)


@pytest.mark.parametrize(
    ("adapter", "field", "reference"),
    [
        ("function", "function", "tests.component_fixtures:Participant"),
        ("agent", "agent_factory", "tests.component_fixtures:lookup_function"),
    ],
)
def test_tool_adapter_reference_has_its_own_signature_contract(
    tmp_path: Path,
    adapter: str,
    field: str,
    reference: str,
) -> None:
    from agentinstruct import TaskValidationError

    root = tmp_path / "task"
    custom_package(root)
    task = root / "task.toml"
    settings = f'type = "{adapter}"\n{field} = "{reference}"'
    if adapter == "agent":
        settings += '\ninstruction = "Return JSON"'
    task.write_text(
        task.read_text().replace('type = "tests.component_fixtures:Lookup"', settings)
    )
    with pytest.raises(TaskValidationError) as error:
        TaskPackage.load(root)
    assert reference in str(error.value)


def test_component_digests_are_part_of_the_immutable_compiled_plan(
    tmp_path: Path,
) -> None:
    package = custom_package(tmp_path / "task")
    plan = next(record.plan for record in package.compile_records())
    assert plan is not None
    digests = plan.provenance.component_digests
    assert {key.split(":", 1)[0] for key in digests} == {
        "agent",
        "environment",
        "tool",
        "reviewer",
        "verifier",
    }
    assert all(
        isinstance(digest, str) and len(digest) == 64 for digest in digests.values()
    )
    independent = plan.to_dict()
    assert "tests.component_fixtures:Participant" in json.dumps(independent)


def test_fixture_runs_through_cli_and_snapshots_its_explicit_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agentinstruct.cli import main

    example = Path(__file__).resolve().parents[1] / "examples/custom-components"
    monkeypatch.syspath_prepend(str(example))
    assert main(["validate", str(example), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {"valid": 2, "invalid": 0}
    assert (
        main(["run", str(example), "--output", str(tmp_path / "runs"), "--json"]) == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["accepted"] == 2
    trace_path = Path(result["traces"][0]["path"])
    assert load_trace(trace_path).status == "accepted"
    source = trace_path.parents[1] / "source-task/round_table_components.py"
    assert source.read_text() == (example / "round_table_components.py").read_text()
    assert main(["reverify", str(trace_path), "--json"]) == 0
    assert len(load_trace(trace_path).verification) == 2
    capsys.readouterr()
