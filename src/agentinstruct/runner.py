"""Canonical asynchronous lifecycle for one seeded generation Run."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import uuid4

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
from agentinstruct.plans import AgentPlan, EnvironmentPlan, ReviewerPlan, VerifierPlan
from agentinstruct.review import Reviewer, ReviewError, ReviewExhausted, create_reviewer
from agentinstruct.store import LocalRunStore, TraceRecorder, load_trace, timestamp
from agentinstruct.task_package import TaskPackage
from agentinstruct.traces import (
    STATUSES,
    ComponentProvenance,
    Event,
    GenerationOutcome,
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
        agent_factory: Callable[[AgentPlan], Agent] = create_agent,
        environment_factory: Callable[[EnvironmentPlan], Environment] | None = None,
        verifier_factory: Callable[[VerifierPlan], Verifier] = create_verifier,
        reviewer_factory: Callable[[ReviewerPlan], Reviewer] = create_reviewer,
    ) -> None:
        self._store = LocalRunStore(output_dir)
        self._agent_factory = agent_factory
        self._environment_factory = environment_factory
        self._verifier_factory = verifier_factory
        self._reviewer_factory = reviewer_factory

    async def run(
        self, package: TaskPackage, *, seed_path: str | Path | None = None
    ) -> RunResult:
        plan = package.compile(seed_path=seed_path)
        run_id, trace_id = uuid4().hex, uuid4().hex
        path = self._store.open_run(run_id, package.source_files)
        recorder = TraceRecorder(path / "traces" / trace_id, plan)
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
        )

        def record(kind: str, **data: str) -> None:
            recorder.event(Event(uuid4().hex, kind, timestamp(), data))

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
            )

        record("trace_started")
        environment: Environment | None = None
        stage = "component_construction"
        deadline = asyncio.timeout(plan.environment.timeout_seconds)
        try:
            handles: dict[str, AgentHandle] = {}
            for agent_id, agent_plan in plan.agents.items():
                agent = self._agent_factory(agent_plan)
                components.append(component_provenance(f"agent:{agent_id}", agent))
                reviewer = None
                if agent_plan.reviewer is not None:
                    reviewer = self._reviewer_factory(agent_plan.reviewer)
                    components.append(
                        component_provenance(f"reviewer:{agent_id}", reviewer)
                    )
                handles[agent_id] = AgentHandle(agent_plan, agent, recorder, reviewer)
            agents = Agents(handles)
            environment = (
                self._environment_factory(plan.environment)
                if self._environment_factory is not None
                else create_environment(plan.environment)
            )
            components.append(component_provenance("environment", environment))
            async with deadline:
                stage = "environment_setup"
                record(stage)
                await environment.setup(agents)
                stage = "environment_run"
                record(stage)
                outcome = await environment.run(context, agents) or outcome
            if outcome.state == "failed":
                status = "failed"
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
        record("generation_finished", state=outcome.state, reason=outcome.reason)
        record("trace_finished", status=status)
        recorder.seal(snapshot())
        if plan.verifier is not None:
            await reverify(recorder.path, verifier_factory=self._verifier_factory)
            status = load_trace(recorder.path).status
        counts: dict[TraceStatus, int] = {key: 0 for key in STATUSES}
        counts[status] = 1
        result = RunResult(
            run_id,
            path,
            (TraceReference(trace_id, plan.seed.id, status, recorder.path),),
            counts,
        )
        self._store.finish_run(result)
        return result


async def generate(
    package: TaskPackage,
    *,
    runner: Runner | None = None,
    seed_path: str | Path | None = None,
) -> RunResult:
    """Convenience entry point with exactly the Runner lifecycle."""
    return await (runner or Runner()).run(package, seed_path=seed_path)


def generate_sync(
    package: TaskPackage,
    *,
    runner: Runner | None = None,
    seed_path: str | Path | None = None,
) -> RunResult:
    """Run from synchronous code; asynchronous callers should await generate."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(generate(package, runner=runner, seed_path=seed_path))
    raise RuntimeError("generate_sync cannot run inside an event loop; await generate")
