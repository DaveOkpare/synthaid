"""Canonical asynchronous lifecycle for one seeded generation Run."""

import asyncio
from collections.abc import Callable, Iterable
from pathlib import Path
from time import monotonic
from typing import Literal, cast
from uuid import uuid4

from agentinstruct.agent_tool import AgentTool
from agentinstruct.components import validate_component
from agentinstruct.execution import (
    Agent,
    AgentHandle,
    Agents,
    Environment,
    FinalizingEnvironment,
    TaskContext,
    create_agent,
    create_environment,
)
from agentinstruct.model_agent import ModelAgent
from agentinstruct.plans import (
    AgentPlan,
    EnvironmentPlan,
    ProviderPlan,
    ReviewerPlan,
    RunPlan,
    TaskIdentity,
    ToolPlan,
    VerifierPlan,
)
from agentinstruct.providers import (
    Provider,
    ProviderError,
    ProviderRequest,
    create_provider,
)
from agentinstruct.quality_provider import QualityCall, quality_request
from agentinstruct.review import (
    ModelReviewer,
    Reviewer,
    ReviewError,
    ReviewExhausted,
    create_reviewer,
)
from agentinstruct.seeds import SeedInput, SeedRecord, SeedSourceError
from agentinstruct.steps import CONTROL_TOOLS, StepProgress
from agentinstruct.store import LocalRunStore, TraceRecorder, load_trace, timestamp
from agentinstruct.task_package import TaskPackage, TaskValidationError
from agentinstruct.tools import FunctionTool, Tool, ToolContext, ToolError, create_tool
from agentinstruct.traces import (
    STATUSES,
    ComponentProvenance,
    Event,
    GenerationOutcome,
    Message,
    RunResult,
    TraceReference,
    TraceSnapshot,
    TraceStatus,
    immutable_data,
)
from agentinstruct.verification import (
    Verifier,
    component_provenance,
    create_verifier,
    reverify,
)


class Runner:
    def __init__(
        self,
        *,
        output_dir: str | Path = "runs",
        agent_factory: Callable[[AgentPlan], Agent] | None = None,
        provider_factory: Callable[[ProviderPlan], Provider] = create_provider,
        environment_factory: Callable[[EnvironmentPlan], Environment] | None = None,
        verifier_factory: Callable[[VerifierPlan], Verifier] = create_verifier,
        reviewer_factory: Callable[[ReviewerPlan], Reviewer] = create_reviewer,
        tool_factory: Callable[[ToolPlan], Tool] = create_tool,
    ) -> None:
        self._store = LocalRunStore(output_dir)
        self._agent_factory = agent_factory
        self._provider_factory = provider_factory
        self._environment_factory = environment_factory
        self._verifier_factory = verifier_factory
        self._reviewer_factory = reviewer_factory
        self._tool_factory = tool_factory

    async def run(
        self,
        package: TaskPackage,
        *,
        seed_path: str | Path | None = None,
        seeds: Iterable[SeedInput] | None = None,
        fail_fast: bool = False,
    ) -> RunResult:
        run_id = uuid4().hex
        path = self._store.open_run(run_id, package.source_files)
        references: list[TraceReference] = []
        counts: dict[TraceStatus, int] = {key: 0 for key in STATUSES}
        status: Literal["finished", "stopped", "failed"] = "finished"
        error = None
        try:
            for compiled in package.compile_records(seed_path=seed_path, seeds=seeds):
                if compiled.plan is None:
                    assert compiled.error is not None
                    reference = self._invalid_trace(
                        compiled.record,
                        compiled.seed_id,
                        run_id,
                        path,
                        TaskValidationError(compiled.error),
                        package.task,
                    )
                else:
                    reference = await self._run_trace(compiled.plan, run_id, path)
                references.append(reference)
                counts[reference.status] += 1
                self._store.index_trace(path, reference)
                if fail_fast and reference.status in {"invalid", "failed"}:
                    status = "stopped"
                    break
        except SeedSourceError as exc:
            status, error = "failed", str(exc)
        except OSError as exc:
            # Advancing would violate the durable snapshot/index boundary.
            # Preserve completed references in the manifest if it remains writable.
            status, error = (
                "failed",
                f"Trace persistence failed ({type(exc).__name__}): {exc}",
            )
        result = RunResult(run_id, path, tuple(references), counts, status, error)
        self._store.finish_run(result)
        return result

    def _invalid_trace(
        self,
        record: SeedRecord,
        seed_id: str,
        run_id: str,
        path: Path,
        error: TaskValidationError,
        task: TaskIdentity,
    ) -> TraceReference:
        trace_id = uuid4().hex
        started_at, started = timestamp(), monotonic()
        recorder = TraceRecorder(path / "traces" / trace_id)
        recorder.event(
            Event(
                uuid4().hex,
                "error",
                timestamp(),
                {
                    "stage": "seed_compilation",
                    "exception": type(error).__name__,
                    "message": str(error),
                },
            )
        )
        recorder.seal(
            TraceSnapshot(
                "1",
                run_id,
                trace_id,
                seed_id,
                "invalid",
                GenerationOutcome("failed", "seed_compilation"),
                {},
                (),
                tuple(recorder.events),
                (),
                started_at,
                timestamp(),
                monotonic() - started,
                seed_record=record,
                task=task,
            )
        )
        return TraceReference(trace_id, seed_id, "invalid", recorder.path)

    async def _run_trace(
        self, plan: RunPlan, run_id: str, path: Path
    ) -> TraceReference:
        trace_id = uuid4().hex
        recorder = TraceRecorder(path / "traces" / trace_id, plan)
        progress = StepProgress(plan.steps, recorder)
        started_at, started = timestamp(), monotonic()
        components: list[ComponentProvenance] = []
        status: TraceStatus = "unverified"
        outcome = GenerationOutcome("terminated", "completed")
        context = TaskContext(
            plan.task,
            plan.seed.id,
            plan.variables,
            plan.environment.max_turns,
            plan.environment.max_rounds,
            plan.environment.timeout_seconds,
            tuple(step.id for step in plan.steps),
        )

        def record(kind: str, **data: str) -> None:
            recorder.event(
                Event(uuid4().hex, kind, timestamp(), data, step_id=progress.step_id)
            )

        def snapshot() -> TraceSnapshot:
            return TraceSnapshot(
                "1",
                run_id,
                trace_id,
                plan.seed.id,
                status,
                outcome,
                immutable_data(plan.to_dict()),
                tuple(recorder.conversation),
                tuple(recorder.events),
                tuple(components),
                started_at,
                timestamp(),
                monotonic() - started,
                task=plan.task,
            )

        record("trace_started")
        environment: Environment | None = None
        providers: dict[str, Provider] = {}
        stage = "component_construction"
        deadline = asyncio.timeout(plan.environment.timeout_seconds)
        try:
            # Build and preflight every used surface before any participant can infer.
            # Custom Agent factories and scripted Tasks require no Provider clients.
            if self._agent_factory is None:
                for agent_plan in plan.agents.values():
                    if agent_plan.type != "model":
                        continue
                    provider_id = agent_plan.model.provider
                    provider_plan = plan.providers[provider_id]
                    if provider_id not in providers:
                        providers[provider_id] = self._provider_factory(provider_plan)
                        components.append(
                            component_provenance(
                                f"provider:{provider_id}", providers[provider_id]
                            )
                        )
                    required_tools = tuple(plan.tools[key] for key in agent_plan.tools)
                    if agent_plan.target and plan.steps:
                        required_tools += tuple(CONTROL_TOOLS.values())
                    providers[provider_id].capabilities.require(
                        provider_plan.api,
                        ProviderRequest(
                            agent_plan.model.name,
                            (Message("system", agent_plan.base_instruction),),
                            required_tools,
                            tool_choice="auto" if required_tools else None,
                            reasoning=agent_plan.model.reasoning,
                        ),
                    )
            quality_plans: list[ReviewerPlan | VerifierPlan] = [
                agent.reviewer
                for agent in plan.agents.values()
                if agent.reviewer is not None
                and agent.reviewer.type == "model"
                and self._reviewer_factory is create_reviewer
            ]
            if (
                plan.verifier is not None
                and plan.verifier.type == "model"
                and self._verifier_factory is create_verifier
            ):
                quality_plans.append(plan.verifier)
            for quality_plan in quality_plans:
                assert (
                    quality_plan.model is not None
                    and quality_plan.structured_output is not None
                )
                provider_id = quality_plan.model.provider
                provider_plan = plan.providers[provider_id]
                if provider_id not in providers:
                    providers[provider_id] = self._provider_factory(provider_plan)
                    components.append(
                        component_provenance(
                            f"provider:{provider_id}", providers[provider_id]
                        )
                    )
                providers[provider_id].capabilities.require(
                    provider_plan.api,
                    quality_request(quality_plan.model, quality_plan.structured_output),
                )
            tools: dict[str, Tool] = {}
            for tool_id, tool_plan in plan.tools.items():
                tool = self._tool_factory(tool_plan)
                validate_component("tool", tool, tool_plan.type)
                if (
                    ToolPlan(
                        tool.id,
                        tool.description,
                        tool.input_schema,
                        tool.output_schema,
                        tool.execution_errors,
                        tool_plan.type,
                        tool_plan.function,
                        tool_plan.agent_factory,
                        tool_plan.instruction,
                        tool_plan.agent_config,
                    )
                    != tool_plan
                ):
                    raise ValueError(
                        "Runtime Tool declaration must match its Tool Plan"
                    )
                tools[tool_id] = tool
                components.append(
                    component_provenance(
                        f"tool:{tool_id}",
                        tool.function
                        if isinstance(tool, FunctionTool)
                        else tool.agent_factory
                        if isinstance(tool, AgentTool)
                        else tool,
                        configuration={
                            "instruction": tool.instruction,
                            "agent_config": tool_plan.agent_config,
                        }
                        if isinstance(tool, AgentTool)
                        else {},
                    )
                )
            handles: dict[str, AgentHandle] = {}
            for agent_id, agent_plan in plan.agents.items():
                agent: Agent
                if self._agent_factory is not None:
                    agent = self._agent_factory(agent_plan)
                elif agent_plan.type == "model":
                    agent = ModelAgent(
                        agent_plan,
                        plan.providers[agent_plan.model.provider],
                        providers[agent_plan.model.provider],
                        record_event=recorder.event,
                        run_id=run_id,
                        trace_id=trace_id,
                    )
                else:
                    agent = create_agent(agent_plan)
                validate_component("agent", agent, agent_plan.type)
                components.append(component_provenance(f"agent:{agent_id}", agent))
                reviewer: Reviewer | None = None
                if agent_plan.reviewer is not None:
                    review_plan = agent_plan.reviewer
                    if (
                        review_plan.type == "model"
                        and self._reviewer_factory is create_reviewer
                    ):
                        assert (
                            review_plan.model is not None
                            and review_plan.structured_output is not None
                        )
                        reviewer = ModelReviewer(
                            QualityCall(
                                review_plan.model,
                                review_plan.structured_output,
                                plan.providers[review_plan.model.provider],
                                providers[review_plan.model.provider],
                                recorder.event,
                                "reviewer",
                            )
                        )
                    else:
                        reviewer = self._reviewer_factory(review_plan)
                    validate_component("reviewer", reviewer, review_plan.type)
                    components.append(
                        component_provenance(f"reviewer:{agent_id}", reviewer)
                    )
                handles[agent_id] = AgentHandle(
                    agent_plan,
                    agent,
                    recorder,
                    reviewer,
                    tools,
                    plan.tools,
                    ToolContext(
                        agent_id,
                        plan.task,
                        plan.seed.id,
                        plan.variables,
                        run_id,
                        trace_id,
                    ),
                    progress,
                )
            agents = Agents(handles)
            environment = (
                self._environment_factory(plan.environment)
                if self._environment_factory is not None
                else create_environment(plan.environment)
            )
            validate_component("environment", environment, plan.environment.type)
            components.append(component_provenance("environment", environment))
            async with deadline:
                progress.start()
                stage = "environment_setup"
                record(stage)
                await environment.setup(agents)
                stage = "environment_run"
                record(stage)
                outcome = await environment.run(context, agents) or outcome
                if (
                    plan.steps
                    and outcome.state == "terminated"
                    and not progress.completed
                ):
                    outcome = GenerationOutcome("truncated", "incomplete_steps")
            if outcome.state == "failed":
                status = "failed"
        except ProviderError as exc:
            status = "failed"
            outcome = GenerationOutcome("failed", f"provider_{exc.kind}")
            record(
                "error",
                stage="provider",
                exception=type(exc).__name__,
                message=str(exc),
            )
        except ToolError as exc:
            status = "failed"
            outcome = GenerationOutcome("failed", f"tool_{exc.kind}")
        except ReviewExhausted:
            outcome = GenerationOutcome("truncated", "review_exhausted")
        except ReviewError as exc:
            status = "failed"
            outcome = GenerationOutcome("failed", f"review_{exc.kind}")
        except Exception as exc:
            if isinstance(exc, TimeoutError) and deadline.expired():
                outcome = GenerationOutcome("truncated", "timeout")
            else:
                status = "failed"
                outcome = GenerationOutcome("failed", stage)
            record("error", stage=stage, exception=type(exc).__name__, message=str(exc))
        finally:
            if environment is not None and hasattr(environment, "finalize"):
                finalization_deadline = asyncio.timeout(
                    plan.environment.timeout_seconds
                )
                try:
                    record("environment_finalize")
                    async with finalization_deadline:
                        await cast(FinalizingEnvironment, environment).finalize(
                            context, snapshot()
                        )
                except Exception as exc:
                    if (
                        isinstance(exc, TimeoutError)
                        and finalization_deadline.expired()
                    ):
                        if outcome.state != "failed":
                            outcome = GenerationOutcome("truncated", "timeout")
                    else:
                        status = "failed"
                        outcome = GenerationOutcome("failed", "environment_finalize")
                    record(
                        "error",
                        stage="environment_finalize",
                        exception=type(exc).__name__,
                        message=str(exc),
                    )
            for provider in providers.values():
                try:
                    await provider.aclose()
                except Exception:
                    status = "failed"
                    outcome = GenerationOutcome("failed", "provider_cleanup")
                    record(
                        "error",
                        stage="provider_cleanup",
                        message="Provider cleanup failed",
                    )
        record("generation_finished", state=outcome.state, reason=outcome.reason)
        record("trace_finished", status=status)
        recorder.seal(snapshot())
        if plan.verifier is not None:
            await reverify(
                recorder.path,
                verifier_factory=self._verifier_factory,
                provider_factory=self._provider_factory,
            )
            status = load_trace(recorder.path).status
        return TraceReference(trace_id, plan.seed.id, status, recorder.path)


async def generate(
    package: TaskPackage,
    *,
    runner: Runner | None = None,
    seed_path: str | Path | None = None,
    seeds: Iterable[SeedInput] | None = None,
    fail_fast: bool = False,
) -> RunResult:
    """Convenience entry point with exactly the Runner lifecycle."""
    return await (runner or Runner()).run(
        package, seed_path=seed_path, seeds=seeds, fail_fast=fail_fast
    )


def generate_sync(
    package: TaskPackage,
    *,
    runner: Runner | None = None,
    seed_path: str | Path | None = None,
    seeds: Iterable[SeedInput] | None = None,
    fail_fast: bool = False,
) -> RunResult:
    """Run from synchronous code; asynchronous callers should await generate."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            generate(
                package,
                runner=runner,
                seed_path=seed_path,
                seeds=seeds,
                fail_fast=fail_fast,
            )
        )
    raise RuntimeError("generate_sync cannot run inside an event loop; await generate")
