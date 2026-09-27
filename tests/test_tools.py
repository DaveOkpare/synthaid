"""Tool behavior through Runner, persisted Traces, and public extensions."""

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from agentinstruct import (
    FunctionCall,
    Message,
    Observation,
    ReviewRequest,
    ReviewResult,
    Runner,
    TaskPackage,
    ToolCall,
    ToolContext,
    ToolPlan,
    export_openai,
    load_trace,
)
from agentinstruct.plans import AgentPlan, FrozenJsonValue, JsonValue


def make_tool_package(
    root: Path, *, assignment: str = 'tools = ["lookup"]'
) -> TaskPackage:
    root.mkdir()
    (root / "task.toml").write_text(
        """schema_version = "1"
[task]
id = "tool-task"
version = "1"
[seed]
path = "seed.json"
[variables]
name = "name"
[providers.default]
type = "openai"
[model]
provider = "default"
name = "unused"
[runtime]
type = "local"
[environment]
type = "single"
[tools.lookup]
description = "Look up a label."
[tools.lookup.input_schema]
type = "object"
properties = { label = { type = "string" } }
required = ["label"]
additionalProperties = false
[tools.lookup.output_schema]
type = "object"
required = ["value", "durable", "actor", "seed"]
additionalProperties = false
[tools.lookup.output_schema.properties]
value = { type = "string" }
durable = { type = "boolean" }
actor = { type = "string" }
seed = { type = "string" }
[agents.assistant]
target = true
"""
        + assignment
        + "\n",
        encoding="utf-8",
    )
    (root / "seed.json").write_text('{"name":"Ada"}')
    (root / "agents/assistant").mkdir(parents=True)
    (root / "agents/assistant/instruction.md").write_text("Use your assigned lookup.")
    return TaskPackage.load(root)


def lookup_message(label: str = "Ada", *, name: str = "lookup") -> Message:
    return Message(
        "assistant",
        "",
        tool_calls=(ToolCall("call-1", FunctionCall(name, {"label": label})),),
    )


class LookupAgent:
    async def generate(self, observation: Observation) -> Message:
        if not observation.messages:
            assert len(observation.tools) == 1
            assert observation.tools[0].id == "lookup"
            return lookup_message()
        result = observation.messages[-1]
        return Message("assistant", "Result: " + result.content)


class LookupTool:
    def __init__(self, plan: ToolPlan, output_dir: Path) -> None:
        self.id = plan.id
        self.description = plan.description
        self.input_schema = plan.input_schema
        self.output_schema = plan.output_schema
        self.output_dir = output_dir

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        journal = next(self.output_dir.glob("*/traces/*/conversation.jsonl"))
        commits = [json.loads(line) for line in journal.read_text().splitlines()]
        accepted = commits[-1]
        return {
            "value": "Hello " + str(args["label"]),
            "durable": accepted["message"]["tool_calls"][0]["id"]
            == context.tool_call_id,
            "actor": context.actor_id,
            "seed": str(context.variables["name"]),
        }


@pytest.mark.asyncio
async def test_tool_commits_intent_before_effect_and_private_result_before_reply(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(make_tool_package(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    assert trace.status == "unverified"
    assert trace.generation.state == "terminated"
    call, response, reply = trace.conversation
    assert call.message.tool_calls == lookup_message().tool_calls
    assert response.message.role == "tool"
    assert response.message.tool_call_id == "call-1"
    assert json.loads(response.message.content) == {
        "value": "Hello Ada",
        "durable": True,
        "actor": "assistant",
        "seed": "Ada",
    }
    assert reply.message.content == "Result: " + response.message.content
    assert [item.visibility for item in trace.conversation] == [
        "private",
        "private",
        "shared",
    ]
    assert response.causal_message_id == call.message.id
    assert len({item.turn_id for item in trace.conversation}) == 1
    assert any(item.kind == "tool:lookup" for item in trace.components)
    tools = trace.run_plan["tools"]
    agents = trace.run_plan["agents"]
    assert isinstance(tools, Mapping) and "lookup" in tools
    assert isinstance(agents, Mapping)
    assistant = agents["assistant"]
    assert isinstance(assistant, Mapping) and assistant["tools"] == ("lookup",)
    dataset = tmp_path / "data.jsonl"
    assert export_openai([result.traces[0].path], dataset, statuses={"unverified"}) == 1
    messages = json.loads(dataset.read_text())["messages"]
    assert messages[0]["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "lookup", "arguments": {"label": "Ada"}},
        }
    ]
    assert messages[1]["role"] == "tool"
    assert messages[1]["tool_call_id"] == "call-1"


class ProposalAgent:
    def __init__(self, proposal: Message) -> None:
        self.proposal = proposal

    async def generate(self, observation: Observation) -> Message:
        if not observation.messages:
            return self.proposal
        return Message("assistant", "Unexpected continuation")


@pytest.mark.asyncio
@pytest.mark.parametrize("assigned", [True, False])
async def test_invalid_arguments_or_assignment_retain_accepted_intent_without_effect(
    tmp_path: Path,
    assigned: bool,
) -> None:
    output = tmp_path / "runs"
    proposal = (
        Message(
            "assistant",
            tool_calls=(ToolCall("bad-args", FunctionCall("lookup", {"label": 123})),),
        )
        if assigned
        else lookup_message()
    )
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: ProposalAgent(proposal),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(
        make_tool_package(
            tmp_path / "task", assignment='tools = ["lookup"]' if assigned else ""
        )
    )

    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed"
    assert trace.generation.reason == (
        "tool_arguments" if assigned else "tool_assignment"
    )
    assert len(trace.conversation) == 1
    assert trace.conversation[0].message.tool_calls == proposal.tool_calls
    error = next(event for event in trace.events if event.kind == "tool_error")
    assert error.data["message_id"] == trace.conversation[0].message.id
    assert error.data["tool_call_id"] == proposal.tool_calls[0].id
    assert not any(event.kind == "tool_started" for event in trace.events)


class InvalidResultTool(LookupTool):
    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        return {"value": 99}


@pytest.mark.asyncio
async def test_invalid_result_fails_after_durable_intent_without_committing_result(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: InvalidResultTool(plan, output),
    ).run(make_tool_package(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed"
    assert trace.generation.reason == "tool_result"
    assert len(trace.conversation) == 1
    assert trace.conversation[0].message.tool_calls == lookup_message().tool_calls
    assert any(event.kind == "tool_started" for event in trace.events)
    error = next(event for event in trace.events if event.kind == "tool_error")
    assert error.data["kind"] == "result"
    assert error.data["tool_call_id"] == "call-1"
    assert export_openai([result.traces[0].path], tmp_path / "data.jsonl") == 0


async def lookup_function(
    args: Mapping[str, FrozenJsonValue], context: ToolContext
) -> JsonValue:
    return {
        "value": "Function " + str(args["label"]),
        "durable": False,
        "actor": context.actor_id,
        "seed": str(context.variables["name"]),
    }


@pytest.mark.asyncio
async def test_function_adapter_uses_tool_contract_and_records_callable_provenance(
    tmp_path: Path,
) -> None:
    from agentinstruct import FunctionTool

    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: FunctionTool(plan, lookup_function),
    ).run(make_tool_package(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert json.loads(trace.conversation[1].message.content)["value"] == "Function Ada"
    provenance = next(item for item in trace.components if item.kind == "tool:lookup")
    assert provenance.reference.endswith(":lookup_function")
    assert provenance.digest is not None and len(provenance.digest) == 64


class ReviewedToolAgent:
    def __init__(self, plan: "AgentPlan") -> None:
        self.plan = plan

    async def generate(self, observation: Observation) -> Message:
        if self.plan.id == "user":
            return Message(
                "assistant",
                json.dumps(
                    {
                        "seen": [message.content for message in observation.messages],
                        "tools": [tool.id for tool in observation.tools],
                        "feedback": observation.review_feedback,
                    }
                ),
                control="complete" if self.plan.target else None,
            )
        if observation.review_feedback == "Use Ada":
            return lookup_message()
        if observation.review_feedback == "Revise reply":
            result = observation.messages[-1]
            return Message("assistant", "Accepted consequence: " + result.content)
        if not observation.messages:
            return lookup_message("rejected argument")
        if observation.messages[-1].role == "tool":
            return Message("assistant", "rejected reply")
        return Message("assistant", "Completed", control="complete")


class ToolReviewer:
    async def review(self, request: "ReviewRequest") -> "ReviewResult":
        from agentinstruct import ReviewResult

        if request.message.tool_calls:
            accepted = (
                request.message.tool_calls[0].function.arguments["label"] == "Ada"
            )
            return ReviewResult({"allowed": accepted}, "Use Ada")
        return ReviewResult(
            {"allowed": request.message.content != "rejected reply"}, "Revise reply"
        )


class CountingLookupTool(LookupTool):
    def __init__(self, plan: ToolPlan, output_dir: Path) -> None:
        super().__init__(plan, output_dir)
        self.count = 0

    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        self.count += 1
        value = await super().call(args, context)
        assert isinstance(value, dict)
        value["value"] = f"{args['label']}: invocation {self.count}"
        return value


def add_tool_review(package: TaskPackage, *, policy: str = "") -> TaskPackage:
    root = package.root
    config = root / "task.toml"
    config.write_text(
        config.read_text() + '\n[agents.assistant.reviewer]\ntype = "custom"\n' + policy
    )
    (root / "agents/assistant/reviewer.md").write_text("Review the call or reply.")
    (root / "agents/assistant/rubric.toml").write_text('[[criteria]]\nid = "allowed"\n')
    return TaskPackage.load(root)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_is_target", [True, False])
async def test_reviewed_tool_and_reply_have_independent_budgets_and_private_projection(
    tmp_path: Path,
    owner_is_target: bool,
) -> None:
    package = make_tool_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text()
        .replace(
            'type = "single"',
            'type = "dialogue"\ninitiator = "assistant"\nmax_rounds = 2',
        )
        .replace("target = true", f"target = {str(owner_is_target).lower()}")
        + f"\n[agents.user]\ntarget = {str(not owner_is_target).lower()}\n"
    )
    (package.root / "agents/user").mkdir()
    (package.root / "agents/user/instruction.md").write_text("Receive the consequence.")
    package = add_tool_review(
        TaskPackage.load(package.root), policy="max_revisions = 1"
    )
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=ReviewedToolAgent,
        reviewer_factory=lambda _: ToolReviewer(),
        tool_factory=lambda plan: CountingLookupTool(plan, output),
    ).run(package)

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    call, response, reply, peer, *_ = trace.conversation
    assert json.loads(response.message.content)["value"] == "Ada: invocation 1"
    assert call.message.tool_calls == lookup_message().tool_calls
    assert reply.message.content.startswith("Accepted consequence:")
    assert json.loads(peer.message.content) == {
        "seen": [reply.message.content],
        "tools": [],
        "feedback": None,
    }
    assert [commit.visibility for commit in (call, response, reply, peer)] == [
        "private",
        "private",
        "shared",
        "shared",
    ]
    assert response.review_id is None
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert [event.data["accepted"] for event in reviews[:4]] == [
        False,
        True,
        False,
        True,
    ]
    assert call.review_id == reviews[1].data["review_id"]
    assert reply.review_id == reviews[3].data["review_id"]
    rejections = [
        event.data["message"] for event in trace.events if event.kind == "rejection"
    ]
    assert len(rejections) == 2
    assert all(
        commit.message.content != "rejected reply" for commit in trace.conversation
    )
    assert (
        "rejected argument"
        not in (result.traces[0].path / "conversation.jsonl").read_text()
    )
    destination = tmp_path / "data.jsonl"
    assert (
        export_openai([result.traces[0].path], destination, statuses={"unverified"})
        == 1
    )
    exported = json.loads(destination.read_text())["messages"]
    assert len(exported) == len(trace.conversation) - (0 if owner_is_target else 2)
    assert any("tool_calls" in message for message in exported) is owner_is_target
    assert any(message["role"] == "tool" for message in exported) is owner_is_target
    assert "rejected argument" not in destination.read_text()
    assert "Revise reply" not in destination.read_text()


class RejectingToolReviewer:
    async def review(self, request: ReviewRequest) -> ReviewResult:
        return ReviewResult({"allowed": False}, "Not permitted")


@pytest.mark.asyncio
async def test_tool_review_exhaustion_never_uses_conversational_fallback(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: ProposalAgent(lookup_message()),
        tool_factory=lambda plan: LookupTool(plan, output),
        reviewer_factory=lambda _: RejectingToolReviewer(),
    ).run(
        add_tool_review(
            make_tool_package(tmp_path / "task"),
            policy="max_revisions = 1\naccept_on_revision_exhaustion = true",
        )
    )

    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "review_exhausted"
    assert trace.conversation == ()
    assert len([event for event in trace.events if event.kind == "rejection"]) == 2
    assert not any(event.kind == "tool_started" for event in trace.events)
    assert export_openai([result.traces[0].path], tmp_path / "data.jsonl") == 0


@pytest.mark.asyncio
async def test_remote_schema_reference_fails_after_acceptance_without_network_retrieval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    attempts: list[object] = []

    def no_network(connection: socket.socket, address: object) -> None:
        attempts.append(address)
        raise AssertionError("Tool schemas may not retrieve remote references")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    package = make_tool_package(tmp_path / "task")
    config = package.root / "task.toml"
    config.write_text(
        config.read_text().replace(
            'properties = { label = { type = "string" } }',
            'properties = { label = { "$ref" = "https://example.invalid/s.json" } }',
        )
    )
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(TaskPackage.load(package.root))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "tool_arguments"
    assert len(trace.conversation) == 1
    error = next(event for event in trace.events if event.kind == "tool_error")
    assert "Unresolvable" in str(error.data["message"])
    assert attempts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("config_change", ["schema", "assignment", "duplicate"])
async def test_invalid_tool_declarations_fail_before_a_run_starts(
    tmp_path: Path,
    config_change: str,
) -> None:
    from agentinstruct import TaskValidationError

    package = make_tool_package(tmp_path / "task")
    config = package.root / "task.toml"
    changes = {
        "schema": ('type = "object"', 'type = "nonexistent"'),
        "assignment": ('tools = ["lookup"]', 'tools = ["unknown"]'),
        "duplicate": ('tools = ["lookup"]', 'tools = ["lookup", "lookup"]'),
    }
    config.write_text(config.read_text().replace(*changes[config_change]))
    with pytest.raises(TaskValidationError):
        await Runner(output_dir=tmp_path / "runs").run(TaskPackage.load(package.root))
    assert not (tmp_path / "runs").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("call_id", ["", " "])
async def test_tool_call_requires_a_stable_nonempty_call_identifier(
    tmp_path: Path,
    call_id: str,
) -> None:
    output = tmp_path / "runs"
    proposal = Message(
        "assistant",
        tool_calls=(ToolCall(call_id, FunctionCall("lookup", {"label": "Ada"})),),
    )
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: ProposalAgent(proposal),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(make_tool_package(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed"
    assert trace.conversation == ()
    assert not any(event.kind == "tool_started" for event in trace.events)


class NonJsonResultTool(LookupTool):
    async def call(
        self, args: Mapping[str, FrozenJsonValue], context: ToolContext
    ) -> JsonValue:
        from typing import cast

        return cast(JsonValue, {123: "not a JSON object key"})


@pytest.mark.asyncio
async def test_tool_result_requires_json_data_even_without_an_output_schema(
    tmp_path: Path,
) -> None:
    package = make_tool_package(tmp_path / "task")
    config = package.root / "task.toml"
    text = config.read_text()
    config.write_text(
        text[: text.index("[tools.lookup.output_schema]")]
        + text[text.index("[agents.assistant]") :]
    )
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: LookupAgent(),
        tool_factory=lambda plan: NonJsonResultTool(plan, output),
    ).run(TaskPackage.load(package.root))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.reason == "tool_result"
    assert len(trace.conversation) == 1


class StaleToolReplyAgent:
    def __init__(self, path: str, *, complete: bool) -> None:
        self.path = path
        self.reply = Message(
            "assistant", "precomputed reply", control="complete" if complete else None
        )

    async def generate(self, observation: Observation) -> Message | list[Message]:
        if self.path == "revised" and observation.review_feedback is None:
            return Message("assistant", "rejected reply")
        if self.path == "continuation" and not observation.messages:
            return lookup_message()
        call_id = "call-2" if observation.messages else "call-1"
        return [
            Message(
                "assistant",
                tool_calls=(
                    ToolCall(call_id, FunctionCall("lookup", {"label": "Ada"})),
                ),
            ),
            self.reply,
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["initial", "revised", "continuation"])
@pytest.mark.parametrize("complete", [False, True])
async def test_tool_call_cannot_accept_a_precomputed_reply_from_the_same_action(
    tmp_path: Path,
    path: str,
    complete: bool,
) -> None:
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: StaleToolReplyAgent(path, complete=complete),
        reviewer_factory=lambda _: ToolReviewer(),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(add_tool_review(make_tool_package(tmp_path / "task")))

    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed"
    assert [commit.message.role for commit in trace.conversation] == (
        ["assistant", "tool"] if path == "continuation" else []
    )
    assert len([event for event in trace.events if event.kind == "tool_started"]) == (
        1 if path == "continuation" else 0
    )
    error = next(event for event in trace.events if event.kind == "error")
    assert "last pending Message" in str(error.data["message"])
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert len(reviews) == (0 if path == "initial" else 1)


class ToolEndingListAgent:
    def __init__(self, *, revised: bool) -> None:
        self.revised = revised

    async def generate(self, observation: Observation) -> Message | list[Message]:
        if not observation.messages:
            if self.revised and observation.review_feedback is None:
                return Message("assistant", "rejected reply")
            return [Message("assistant", "preamble"), lookup_message()]
        result = observation.messages[-1]
        return [
            Message(
                "assistant",
                json.dumps(
                    {
                        "roles": [message.role for message in observation.messages],
                        "result": json.loads(result.content)["value"],
                        "call_id": result.tool_call_id,
                        "feedback": observation.review_feedback,
                    }
                ),
            ),
            Message("assistant", "Completed", control="complete"),
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("revised", [False, True])
async def test_valid_tool_ending_lists_generate_fresh_reply_lists_from_the_exchange(
    tmp_path: Path,
    revised: bool,
) -> None:
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: ToolEndingListAgent(revised=revised),
        reviewer_factory=lambda _: ToolReviewer(),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(add_tool_review(make_tool_package(tmp_path / "task")))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    preamble, call, response, reply, complete = trace.conversation
    assert preamble.message.content == "preamble"
    assert call.message.tool_calls == lookup_message().tool_calls
    assert response.message.tool_call_id == "call-1"
    assert json.loads(reply.message.content) == {
        "roles": ["assistant", "assistant", "tool"],
        "result": "Hello Ada",
        "call_id": "call-1",
        "feedback": None,
    }
    assert complete.message.control == "complete"
    reviews = [event for event in trace.events if event.kind == "review_result"]
    assert [event.data["accepted"] for event in reviews] == (
        ([False] if revised else []) + [True, True, True, True]
    )
    assert len({commit.review_id for commit in (preamble, call, reply, complete)}) == 4
    assert response.review_id is None


class ToolRevisionBeforePendingReplyAgent:
    async def generate(self, observation: Observation) -> Message | list[Message]:
        if observation.review_feedback is None:
            return [
                Message("assistant", "rejected reply"),
                Message("assistant", "original pending reply"),
            ]
        return [lookup_message()]


@pytest.mark.asyncio
async def test_tool_revision_cannot_skip_an_older_pending_reply(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs"
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: ToolRevisionBeforePendingReplyAgent(),
        reviewer_factory=lambda _: ToolReviewer(),
        tool_factory=lambda plan: LookupTool(plan, output),
    ).run(add_tool_review(make_tool_package(tmp_path / "task")))

    trace = load_trace(result.traces[0].path)
    assert trace.status == "failed"
    assert trace.conversation == ()
    error = next(event for event in trace.events if event.kind == "error")
    assert "last pending Message" in str(error.data["message"])
    assert not any(event.kind == "tool_started" for event in trace.events)
