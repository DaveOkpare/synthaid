"""Task Steps through the public Runner and recorded Trace boundary."""

import json
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from agentinstruct import (
    Agents,
    FunctionCall,
    FunctionTool,
    Message,
    Observation,
    ReviewRequest,
    ReviewResult,
    Runner,
    TaskContext,
    TaskPackage,
    TaskValidationError,
    ToolCall,
    ToolContext,
    export_openai,
    load_trace,
)
from agentinstruct.plans import FrozenJsonValue, JsonValue
from agentinstruct.traces import GenerationOutcome


def step_package(root: Path) -> TaskPackage:
    root.mkdir()
    (root / "task.toml").write_text("""schema_version = "1"
[task]
id = "stepped"
version = "1"
steps = ["collect", "conclude"]
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
max_turns = 4
[agents.assistant]
target = true
""")
    (root / "seed.json").write_text('{"name":"Ada"}')
    for directory, text in (
        ("agents/assistant", "Base {{ name }}."),
        ("steps/collect/agents/assistant", "Collect {{ name }}."),
        ("steps/conclude/agents/assistant", "Conclude {{ name }}."),
    ):
        path = root / directory
        path.mkdir(parents=True)
        (path / "instruction.md").write_text(text)
    return TaskPackage.load(root)


def control(name: str, step: str | None = None, *, call_id: str = "control") -> Message:
    return Message(
        "assistant",
        tool_calls=(
            ToolCall(
                call_id, FunctionCall(name, {} if step is None else {"step_id": step})
            ),
        ),
    )


class SteppedAgent:
    def __init__(self) -> None:
        self.seen: list[Observation] = []
        self.actions = iter(
            (
                Message("assistant", "Collected Ada."),
                control("advance_step", "conclude", call_id="advance"),
                control("complete_task", call_id="complete"),
                Message("assistant", "Concluded Ada."),
            )
        )

    async def generate(self, observation: Observation) -> Message:
        self.seen.append(observation)
        return next(self.actions)


@pytest.mark.asyncio
async def test_steps_replace_additions_and_keep_accepted_history(
    tmp_path: Path,
) -> None:
    agent = SteppedAgent()
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: agent
    ).run(step_package(tmp_path / "task"))

    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert [observation.instruction for observation in agent.seen] == [
        "Base Ada.\n\nCollect Ada.",
        "Base Ada.\n\nCollect Ada.",
        "Base Ada.\n\nConclude Ada.",
        "Base Ada.\n\nConclude Ada.",
    ]
    assert agent.seen[-1].messages[0].content == "Collected Ada."
    assert [tool.id for tool in agent.seen[0].tools] == ["advance_step"]
    assert [tool.id for tool in agent.seen[2].tools] == ["complete_task"]
    assert agent.seen[-1].tools == ()
    assert [commit.step_id for commit in trace.conversation] == [
        "collect",
        "collect",
        "collect",
        "conclude",
        "conclude",
        "conclude",
    ]
    assert [
        event.step_id for event in trace.events if event.kind == "step_started"
    ] == ["collect", "conclude"]
    assert trace.conversation[2].message.tool_call_id == "advance"
    assert trace.conversation[4].message.tool_call_id == "complete"
    assert all(commit.message.control is None for commit in trace.conversation)
    assert (
        result.path / "source-task/steps/conclude/agents/assistant/instruction.md"
    ).is_file()


def add_review(package: TaskPackage) -> TaskPackage:
    root = package.root
    with (root / "task.toml").open("a") as stream:
        stream.write("""
[agents.assistant.reviewer]
type = "custom"
max_revisions = 0
accept_on_revision_exhaustion = true
""")
    (root / "agents/assistant/reviewer.md").write_text("Review {{ name }}.")
    (root / "agents/assistant/rubric.toml").write_text("""threshold = 0.5
[[criteria]]
id = "base"
weight = 1.0
""")
    for step, criterion in (("collect", "collected"), ("conclude", "concluded")):
        (root / f"steps/{step}/agents/assistant/rubric.toml").write_text(
            f'[[criteria]]\nid = "{criterion}"\nweight = 1.0\n'
        )
    return TaskPackage.load(root)


class ActiveReviewer:
    def __init__(self) -> None:
        self.requests: list[ReviewRequest] = []

    async def review(self, request: ReviewRequest) -> ReviewResult:
        self.requests.append(request)
        return ReviewResult(
            {
                criterion.id: criterion.id == "base"
                for criterion in request.rubric.criteria
            }
        )


@pytest.mark.asyncio
async def test_active_review_appends_only_current_criteria_and_retains_threshold(
    tmp_path: Path,
) -> None:
    reviewer = ActiveReviewer()
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: SteppedAgent(),
        reviewer_factory=lambda _: reviewer,
    ).run(add_review(step_package(tmp_path / "task")))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert [tuple(c.id for c in r.rubric.criteria) for r in reviewer.requests] == [
        ("base", "collected"),
        ("base", "collected"),
        ("base", "concluded"),
        ("base", "concluded"),
    ]
    assert [r.rubric.threshold for r in reviewer.requests] == [0.5] * 4
    assert [r.agent_instruction for r in reviewer.requests] == [
        "Base Ada.\n\nCollect Ada.",
        "Base Ada.\n\nCollect Ada.",
        "Base Ada.\n\nConclude Ada.",
        "Base Ada.\n\nConclude Ada.",
    ]
    assert [e.step_id for e in trace.events if e.kind == "review_result"] == [
        "collect",
        "collect",
        "conclude",
        "conclude",
    ]


class FixedAgent:
    def __init__(self, proposal: Message) -> None:
        self.proposal = proposal

    async def generate(self, observation: Observation) -> Message:
        return self.proposal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proposal",
    [
        Message("assistant", "Done", control="complete"),
        Message(
            "assistant",
            tool_calls=(
                ToolCall("one", FunctionCall("advance_step", {"step_id": "conclude"})),
                ToolCall("two", FunctionCall("complete_task", {})),
            ),
        ),
        Message(
            "assistant",
            tool_calls=(
                ToolCall("one", FunctionCall("advance_step", {"step_id": "conclude"})),
                ToolCall("two", FunctionCall("lookup", {})),
            ),
        ),
    ],
)
async def test_invalid_control_shapes_cannot_change_step(
    tmp_path: Path, proposal: Message
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: FixedAgent(proposal)
    ).run(step_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "failed"
    assert trace.conversation == ()
    assert [e.step_id for e in trace.events if e.kind == "step_started"] == ["collect"]


def change_config(root: Path, old: str, new: str) -> None:
    path = root / "task.toml"
    path.write_text(path.read_text().replace(old, new))


def extra_step(root: Path) -> None:
    (root / "steps/undeclared").mkdir()


def extra_agent(root: Path) -> None:
    (root / "steps/collect/agents/undeclared").mkdir()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda root: change_config(
            root, '["collect", "conclude"]', '["collect", "collect"]'
        ),
        lambda root: change_config(
            root, '["collect", "conclude"]', '["collect", "COLLECT"]'
        ),
        lambda root: change_config(
            root, '["collect", "conclude"]', '["CON", "conclude"]'
        ),
        lambda root: change_config(root, 'steps = ["collect", "conclude"]', ""),
        extra_step,
        extra_agent,
        lambda root: (root / "steps/conclude/agents/assistant/instruction.md").unlink(),
        lambda root: change_config(
            root,
            "[agents.assistant]",
            '[tools.advance_step]\ndescription="Collision"\ninput_schema=true\n[agents.assistant]',
        ),
        lambda root: change_config(
            root,
            "[agents.assistant]",
            '[tools.Complete_Task]\ndescription="Collision"\ninput_schema=true\n[agents.assistant]',
        ),
    ],
)
async def test_step_layout_and_control_collisions_fail_before_generation(
    tmp_path: Path,
    mutate: Callable[[Path], None],
) -> None:
    package = step_package(tmp_path / "task")
    mutate(package.root)
    agent = SteppedAgent()
    with pytest.raises(TaskValidationError):
        await Runner(output_dir=tmp_path / "runs", agent_factory=lambda _: agent).run(
            TaskPackage.load(package.root)
        )
    assert agent.seen == []


class EnvironmentControl:
    def __init__(self, action: str = "advance", *, attempt: str = "control") -> None:
        self.action = action
        self.attempt = attempt

    async def setup(self, agents: Agents) -> None:
        pass

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        if self.attempt == "return":
            return GenerationOutcome("terminated", "claimed_complete")
        async with agents["assistant"].interaction(task) as interaction:
            proposal = (
                task.advance_step("conclude")
                if self.action == "advance"
                else task.complete_task()
            )
            await interaction.control(proposal)
        return GenerationOutcome("terminated", "completed")


class RejectControls:
    async def review(self, request: ReviewRequest) -> ReviewResult:
        return ReviewResult(
            {criterion.id: False for criterion in request.rubric.criteria},
            "Stay in this step.",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["advance", "complete"])
@pytest.mark.parametrize("from_environment", [False, True])
async def test_rejected_controls_never_use_exhaustion_fallback(
    tmp_path: Path,
    action: str,
    from_environment: bool,
) -> None:
    package = add_review(step_package(tmp_path / "task"))
    proposal = (
        control("advance_step", "conclude")
        if action == "advance"
        else control("complete_task")
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: FixedAgent(proposal),
        reviewer_factory=lambda _: RejectControls(),
        environment_factory=(lambda _: EnvironmentControl(action))
        if from_environment
        else None,
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.generation == GenerationOutcome("truncated", "review_exhausted")
    assert trace.conversation == ()
    assert [e.step_id for e in trace.events if e.kind == "step_started"] == ["collect"]
    assert any(
        e.kind == "review_exhausted" and e.data["accepted"] is False
        for e in trace.events
    )
    assert not any(e.kind == "task_completed" for e in trace.events)


@pytest.mark.asyncio
async def test_environment_cannot_claim_completion_without_reviewed_control(
    tmp_path: Path,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: SteppedAgent(),
        environment_factory=lambda _: EnvironmentControl(attempt="return"),
    ).run(step_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation == GenerationOutcome("truncated", "incomplete_steps")


class SequenceAgent:
    def __init__(self, actions: list[Message | list[Message]]) -> None:
        self.actions = iter(actions)
        self.seen: list[Observation] = []

    async def generate(self, observation: Observation) -> Message | list[Message]:
        self.seen.append(observation)
        return next(self.actions)


@pytest.mark.asyncio
async def test_environment_advance_is_reviewed_and_continues_with_new_step(
    tmp_path: Path,
) -> None:
    agent = SequenceAgent([control("complete_task"), Message("assistant", "Done.")])
    reviewer = ActiveReviewer()
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: agent,
        reviewer_factory=lambda _: reviewer,
        environment_factory=lambda _: EnvironmentControl(),
    ).run(add_review(step_package(tmp_path / "task")))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert [r.step_id for r in reviewer.requests] == ["collect", "conclude", "conclude"]
    assert agent.seen[0].step_id == "conclude"
    assert agent.seen[0].messages[-1].role == "tool"
    assert trace.conversation[0].review_id is not None
    assert trace.conversation[0].step_id == trace.conversation[1].step_id == "collect"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "proposal,reason",
    [
        (control("complete_task"), "tool_execution"),
        (control("advance_step", "collect"), "tool_execution"),
        (control("advance_step", "missing"), "tool_execution"),
        (control("advance_step"), "tool_arguments"),
    ],
)
async def test_invalid_progress_retains_durable_intent_without_changing_step(
    tmp_path: Path,
    proposal: Message,
    reason: str,
) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs", agent_factory=lambda _: FixedAgent(proposal)
    ).run(step_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation == GenerationOutcome("failed", reason)
    assert len(trace.conversation) == 1
    assert trace.conversation[0].message.tool_calls == proposal.tool_calls
    assert trace.conversation[0].step_id == "collect"
    assert [e.step_id for e in trace.events if e.kind == "step_started"] == ["collect"]


def dialogue_package(root: Path) -> TaskPackage:
    package = step_package(root)
    change_config(
        root, 'type = "single"\nmax_turns = 4', 'type = "dialogue"\nmax_rounds = 4'
    )
    change_config(root, "target = true", 'target = true\ntools = ["lookup"]')
    with (root / "task.toml").open("a") as stream:
        stream.write("""
[agents.user]
target = false
tools = ["lookup"]
[tools.lookup]
description = "A private label."
input_schema = { type = "object", additionalProperties = false }
""")
    for directory, text in (
        ("agents/user", "User base {{ name }}."),
        ("steps/collect/agents/user", "User collect {{ name }}."),
        ("steps/conclude/agents/user", "User conclude {{ name }}."),
    ):
        path = package.root / directory
        path.mkdir(parents=True)
        (path / "instruction.md").write_text(text)
    return TaskPackage.load(root)


async def private_lookup(
    args: Mapping[str, FrozenJsonValue], context: ToolContext
) -> JsonValue:
    return {"actor": context.actor_id, "step": context.step_id}


@pytest.mark.asyncio
async def test_both_agents_keep_private_tools_and_shared_history_across_steps(
    tmp_path: Path,
) -> None:
    package = dialogue_package(tmp_path / "task")
    user = SequenceAgent(
        [
            control("lookup", call_id="user-lookup"),
            Message("assistant", "User earlier."),
            Message("assistant", "User prompt."),
            Message("assistant", "User later."),
        ]
    )
    assistant = SequenceAgent(
        [
            control("lookup", call_id="assistant-lookup"),
            Message("assistant", "Assistant earlier."),
            control("advance_step", "conclude", call_id="advance"),
            Message("assistant", "Assistant later."),
            control("complete_task", call_id="complete"),
            Message("assistant", "Assistant final."),
        ]
    )
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda plan: user if plan.id == "user" else assistant,
        tool_factory=lambda plan: FunctionTool(plan, private_lookup),
    ).run(package)
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    for actor, agent in (("user", user), ("assistant", assistant)):
        final = agent.seen[-1]
        assert final.step_id == "conclude"
        assert "Collect" not in final.instruction and "collect" not in final.instruction
        assert {m.content for m in final.messages} >= {
            "User earlier.",
            "Assistant earlier.",
        }
        assert {
            m.actor_id for m in final.messages if m.tool_calls or m.role == "tool"
        } == {actor}
        assert any(m.tool_call_id == f"{actor}-lookup" for m in final.messages)
    assert not any(
        tool.id in {"advance_step", "complete_task"} for tool in user.seen[-1].tools
    )
    results = [
        c
        for c in trace.conversation
        if c.message.tool_call_id in {"user-lookup", "assistant-lookup"}
    ]
    assert [json.loads(c.message.content) for c in results] == [
        {"actor": "user", "step": "collect"},
        {"actor": "assistant", "step": "collect"},
    ]
    assert all(c.step_id == "collect" for c in results)
    output = tmp_path / "dataset.jsonl"
    assert export_openai([result.traces[0].path], output, statuses={"unverified"}) == 1
    exported = json.loads(output.read_text())["messages"]
    assert [m["tool_call_id"] for m in exported if m["role"] == "tool"] == [
        "assistant-lookup",
        "advance",
        "complete",
    ]


@pytest.mark.asyncio
async def test_simulator_cannot_advance_even_without_reviewer(tmp_path: Path) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: FixedAgent(control("advance_step", "conclude")),
        tool_factory=lambda plan: FunctionTool(plan, private_lookup),
    ).run(dialogue_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation == GenerationOutcome("failed", "tool_assignment")
    assert len(trace.conversation) == 1
    assert trace.conversation[0].message.actor_id == "user"
    assert [e.step_id for e in trace.events if e.kind == "step_started"] == ["collect"]


@pytest.mark.asyncio
@pytest.mark.parametrize("template", ["{{ name.missing }}", "{{ unknown }}"])
async def test_later_step_templates_fail_before_first_generation(
    tmp_path: Path, template: str
) -> None:
    package = step_package(tmp_path / "task")
    (package.root / "steps/conclude/agents/assistant/instruction.md").write_text(
        template
    )
    agent = SteppedAgent()
    with pytest.raises(
        TaskValidationError,
        match=r"steps/conclude/agents/assistant/instruction\.md:",
    ):
        await Runner(output_dir=tmp_path / "runs", agent_factory=lambda _: agent).run(
            TaskPackage.load(package.root)
        )
    assert agent.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rubric",
    [
        'threshold = 0.1\n[[criteria]]\nid = "extra"\n',
        '[[criteria]]\nid = "base"\n',
        '[[criteria]]\nid = "extra"\n[[criteria]]\nid = "extra"\n',
    ],
)
async def test_step_rubric_cannot_override_threshold_or_duplicate_criteria(
    tmp_path: Path, rubric: str
) -> None:
    package = add_review(step_package(tmp_path / "task"))
    (package.root / "steps/conclude/agents/assistant/rubric.toml").write_text(rubric)
    agent = SteppedAgent()
    with pytest.raises(TaskValidationError):
        await Runner(output_dir=tmp_path / "runs", agent_factory=lambda _: agent).run(
            TaskPackage.load(package.root)
        )
    assert agent.seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["outside", "cycle"])
async def test_step_instruction_links_are_safe_before_generation(
    tmp_path: Path, kind: str
) -> None:
    package = step_package(tmp_path / "task")
    instruction = package.root / "steps/conclude/agents/assistant/instruction.md"
    instruction.unlink()
    outside = tmp_path / "outside.md"
    outside.write_text("Outside")
    instruction.symlink_to(outside if kind == "outside" else instruction)
    agent = SteppedAgent()
    with pytest.raises(TaskValidationError):
        await Runner(output_dir=tmp_path / "runs", agent_factory=lambda _: agent).run(
            TaskPackage.load(package.root)
        )
    assert agent.seen == []


class RejectFirst:
    def __init__(self) -> None:
        self.requests: list[ReviewRequest] = []

    async def review(self, request: ReviewRequest) -> ReviewResult:
        self.requests.append(request)
        accepted = len(self.requests) > 1
        return ReviewResult(
            {criterion.id: accepted for criterion in request.rubric.criteria},
            "Revise the proposal." if not accepted else "",
        )


@pytest.mark.asyncio
async def test_revised_advance_keeps_old_step_until_accepted(tmp_path: Path) -> None:
    package = add_review(step_package(tmp_path / "task"))
    change_config(package.root, "max_revisions = 0", "max_revisions = 1")
    agent = SequenceAgent(
        [
            control("advance_step", "conclude", call_id="rejected"),
            control("advance_step", "conclude", call_id="accepted"),
            control("complete_task", call_id="complete"),
            Message("assistant", "Done."),
        ]
    )
    reviewer = RejectFirst()
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: agent,
        reviewer_factory=lambda _: reviewer,
    ).run(TaskPackage.load(package.root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "terminated"
    assert [r.step_id for r in reviewer.requests] == [
        "collect",
        "collect",
        "conclude",
        "conclude",
    ]
    assert agent.seen[1].review_feedback == "Revise the proposal."
    assert agent.seen[1].messages == ()
    assert agent.seen[1].instruction == "Base Ada.\n\nCollect Ada."
    assert [
        call.id for commit in trace.conversation for call in commit.message.tool_calls
    ] == ["accepted", "complete"]
    assert [e.step_id for e in trace.events if e.kind == "step_started"] == [
        "collect",
        "conclude",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase", ["initial", "revision", "continuation", "retained-tail"]
)
async def test_control_calls_cannot_leave_stale_pending_messages(
    tmp_path: Path, phase: str
) -> None:
    package = add_review(step_package(tmp_path / "task"))
    change_config(package.root, "max_revisions = 0", "max_revisions = 1")
    advance = control("advance_step", "conclude", call_id="advance")
    tail = Message("assistant", "Precomputed reply.")
    actions: list[Message | list[Message]]
    if phase == "continuation":
        actions = [advance, [control("complete_task"), tail]]
    elif phase == "revision":
        actions = [Message("assistant", "Rejected."), [advance, tail]]
    elif phase == "retained-tail":
        actions = [[Message("assistant", "Rejected."), tail], advance]
    else:
        actions = [[advance, tail]]
    agent = SequenceAgent(actions)
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: agent,
        reviewer_factory=lambda _: (
            RejectFirst()
            if phase in {"revision", "retained-tail"}
            else ActiveReviewer()
        ),
    ).run(TaskPackage.load(package.root))
    trace = load_trace(result.traces[0].path)
    assert trace.generation.state == "failed"
    assert not any(e.kind == "task_completed" for e in trace.events)
    assert not any(
        c.message.content == "Precomputed reply." for c in trace.conversation
    )
    assert len(trace.conversation) == (2 if phase == "continuation" else 0)


@pytest.mark.asyncio
async def test_step_without_completion_truncates_at_turn_limit(tmp_path: Path) -> None:
    result = await Runner(
        output_dir=tmp_path / "runs",
        agent_factory=lambda _: FixedAgent(Message("assistant", "Still working.")),
    ).run(step_package(tmp_path / "task"))
    trace = load_trace(result.traces[0].path)
    assert trace.generation == GenerationOutcome("truncated", "max_turns")
    assert len(trace.conversation) == 4
