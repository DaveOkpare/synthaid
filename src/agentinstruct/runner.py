"""Canonical asynchronous lifecycle for one seeded generation Run."""

import asyncio
import hashlib
import inspect
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
    SingleAgentEnvironment,
    TaskContext,
    create_agent,
)
from agentinstruct.plans import AgentPlan, EnvironmentPlan
from agentinstruct.store import LocalRunStore, TraceRecorder, timestamp
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


def component_provenance(kind: str, component: object) -> ComponentProvenance:
    cls = type(component)
    try:
        source = inspect.getsource(cls).encode("utf-8")
        digest = hashlib.sha256(source).hexdigest()
    except (OSError, TypeError):
        digest = None
    return ComponentProvenance(kind, f"{cls.__module__}:{cls.__qualname__}", digest)


class Runner:
    def __init__(
        self,
        *,
        output_dir: str | Path = "runs",
        agent_factory: Callable[[AgentPlan], Agent] = create_agent,
        environment_factory: Callable[[EnvironmentPlan], Environment] | None = None,
    ) -> None:
        self._store = LocalRunStore(output_dir)
        self._agent_factory = agent_factory
        self._environment_factory = environment_factory

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
            plan.task, plan.seed.id, plan.variables, plan.environment.max_turns
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
        try:
            handles: dict[str, AgentHandle] = {}
            for agent_id, agent_plan in plan.agents.items():
                agent = self._agent_factory(agent_plan)
                components.append(component_provenance(f"agent:{agent_id}", agent))
                handles[agent_id] = AgentHandle(agent_plan, agent, recorder)
            agents = Agents(handles)
            environment = (
                self._environment_factory(plan.environment)
                if self._environment_factory is not None
                else SingleAgentEnvironment()
            )
            components.append(component_provenance("environment", environment))
            stage = "environment_setup"
            record(stage)
            await environment.setup(agents)
            stage = "environment_run"
            record(stage)
            outcome = await environment.run(context, agents) or outcome
            if outcome.state == "failed":
                status = "failed"
        except Exception as exc:
            status = "failed"
            outcome = GenerationOutcome("failed", stage)
            record("error", stage=stage, exception=type(exc).__name__, message=str(exc))
        finally:
            if environment is not None and hasattr(environment, "finalize"):
                try:
                    record("environment_finalize")
                    await cast(FinalizingEnvironment, environment).finalize(
                        context, snapshot()
                    )
                except Exception as exc:
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
