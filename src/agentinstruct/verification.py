"""Post-generation Verification over sealed immutable Trace snapshots."""

import asyncio
import hashlib
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Literal, Protocol, cast
from uuid import uuid4

from pydantic import TypeAdapter

from agentinstruct.components import validate_component
from agentinstruct.plans import (
    FrozenJsonValue,
    ProviderPlan,
    Seed,
    VerifierPlan,
    canonical_json,
)
from agentinstruct.providers import Provider, ProviderError, create_provider
from agentinstruct.quality import Verdicts, score_verdicts
from agentinstruct.quality_provider import QualityCall, quality_request
from agentinstruct.store import (
    load_trace,
    timestamp,
    verification_directory,
    write_json,
)
from agentinstruct.traces import (
    ComponentProvenance,
    Event,
    TraceSnapshot,
    VerificationAttempt,
    VerificationError,
)

if TYPE_CHECKING:
    from agentinstruct.task_package import TaskPackage


def component_provenance(
    kind: str,
    component: object,
    *,
    configuration: Mapping[str, FrozenJsonValue] | None = None,
) -> ComponentProvenance:
    while isinstance(component, partial):
        component = component.func
    cls = (
        component
        if inspect.isfunction(component)
        or inspect.ismethod(component)
        or inspect.isbuiltin(component)
        or inspect.isclass(component)
        else type(component)
    )
    try:
        source = inspect.getsource(cls).encode("utf-8")
        digest = hashlib.sha256(source).hexdigest()
    except (OSError, TypeError):
        digest = None
    return ComponentProvenance(
        kind, f"{cls.__module__}:{cls.__qualname__}", digest, configuration or {}
    )


@dataclass(frozen=True)
class VerificationResult:
    criteria: Verdicts
    feedback: str = ""


class Verifier(Protocol):
    async def verify(self, trace: TraceSnapshot) -> VerificationResult: ...


class ModelVerifier:
    def __init__(self, plan: VerifierPlan, call: QualityCall) -> None:
        self.plan, self.call = plan, call

    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        decision = await self.call.evaluate(
            self.plan.instruction,
            {
                "rubric": self.plan.rubric,
                "task": trace.task,
                "seed": trace.run_plan.get("seed"),
                "generation": trace.generation,
                "conversation": trace.conversation,
            },
            self.plan.rubric,
        )
        return VerificationResult(
            [(item.id, item.passed) for item in decision.criteria], decision.feedback
        )


class DeterministicVerifier:
    """Small declared checks for offline generation and smoke-test Tasks."""

    def __init__(self, plan: VerifierPlan) -> None:
        self.plan = plan

    async def verify(self, trace: TraceSnapshot) -> VerificationResult:
        outcomes = {
            "nonempty_conversation": bool(trace.conversation),
            "generation_terminated": trace.generation.state == "terminated",
        }
        return VerificationResult(
            {
                identifier: outcomes[check]
                for identifier, check in self.plan.checks.items()
            }
        )


def create_verifier(plan: VerifierPlan) -> Verifier:
    from agentinstruct.components import construct_component

    return cast(Verifier, construct_component("verifier", plan.type, plan))


async def reverify(
    path: str | Path,
    *,
    plan: VerifierPlan | None = None,
    verifier_factory: Callable[[VerifierPlan], Verifier] = create_verifier,
    provider_factory: Callable[[ProviderPlan], Provider] = create_provider,
    provider_plan: ProviderPlan | None = None,
    package: "TaskPackage | None" = None,
) -> VerificationAttempt:
    """Append a quality decision without changing any sealed generation files."""
    trace = load_trace(path)
    if package is not None:
        if plan is not None or provider_plan is not None:
            raise ValueError("Choose a Task Package or explicit Verifier Plan override")
        plan = package.verifier
        if plan is None:
            raise ValueError("Selected Task Package has no Verifier policy")
        if plan.type == "model":
            stored_seed = trace.run_plan.get("seed")
            if stored_seed is None:
                raise ValueError("Model Verifier override requires a persisted Seed")
            seed = TypeAdapter(Seed).validate_json(canonical_json(stored_seed))
            plan = package.compile_seed(seed).verifier
            assert plan is not None and plan.model is not None
            provider_plan = package.providers[plan.model.provider]
    if plan is None:
        stored_plan = trace.run_plan.get("verifier")
        if stored_plan is None:
            raise ValueError("Trace has no Verifier Plan; supply one to reverify")
        plan = TypeAdapter(VerifierPlan).validate_json(canonical_json(stored_plan))
    started_at, started = timestamp(), monotonic()
    provenance = ComponentProvenance("verifier", plan.type, None)
    status: Literal["accepted", "rejected", "unverified"] = "unverified"
    score = None
    criteria: dict[str, bool] = {}
    feedback = ""
    error = None
    stage: Literal["execution", "malformed", "timeout"] = "execution"
    deadline = asyncio.timeout(plan.timeout_seconds)
    provider = None
    verifier: Verifier
    events: list[Event] = []
    try:
        async with deadline:
            if plan.type == "model" and verifier_factory is create_verifier:
                assert plan.model is not None and plan.structured_output is not None
                if provider_plan is None:
                    stored_providers = trace.run_plan["providers"]
                    assert isinstance(stored_providers, Mapping)
                    provider_plan = TypeAdapter(ProviderPlan).validate_json(
                        canonical_json(stored_providers[plan.model.provider])
                    )
                if provider_plan.id != plan.model.provider:
                    raise ValueError(
                        "Verifier Provider must match the model's declared Provider"
                    )
                provider = provider_factory(provider_plan)
                provider.capabilities.require(
                    provider_plan.api,
                    quality_request(plan.model, plan.structured_output),
                )
                verifier = ModelVerifier(
                    plan,
                    QualityCall(
                        plan.model,
                        plan.structured_output,
                        provider_plan,
                        provider,
                        events.append,
                        "verifier",
                    ),
                )
            else:
                verifier = verifier_factory(plan)
            validate_component("verifier", verifier, plan.type)
            provenance = component_provenance("verifier", verifier)
            result = await verifier.verify(trace)
        stage = "malformed"
        if not isinstance(result, VerificationResult) or not isinstance(
            result.feedback, str
        ):
            raise ValueError(
                "Verifier must return a VerificationResult with text feedback"
            )
        score = score_verdicts(plan.rubric, result.criteria)
        criteria = dict(result.criteria)
        feedback = result.feedback
        status = "accepted" if score >= plan.rubric.threshold else "rejected"
    except Exception as exc:
        score, criteria, feedback = None, {}, ""
        if isinstance(exc, TimeoutError) and deadline.expired():
            stage = "timeout"
        if isinstance(exc, ProviderError) and exc.kind in {
            "invalid_json",
            "schema_mismatch",
        }:
            stage = "malformed"
        error = VerificationError(
            stage,
            type(exc).__name__,
            str(exc),
            exc.kind if isinstance(exc, ProviderError) else None,
        )
    finally:
        if provider is not None:
            try:
                await provider.aclose()
            except Exception:
                score, criteria, feedback, status = None, {}, "", "unverified"
                error = VerificationError(
                    "execution",
                    "ProviderError",
                    "Verifier Provider cleanup failed",
                    "unknown",
                )
    attempt = VerificationAttempt(
        schema_version="1",
        id=uuid4().hex,
        trace_id=trace.trace_id,
        sequence=len(trace.verification) + 1,
        plan=plan,
        verifier=provenance,
        status=status,
        score=score,
        criteria=criteria,
        feedback=feedback,
        started_at=started_at,
        ended_at=timestamp(),
        duration_seconds=monotonic() - started,
        error=error,
        events=tuple(events),
        provider=provider_plan,
    )
    attempts = verification_directory(path)
    attempts.mkdir(exist_ok=True)
    write_json(attempts / f"{attempt.id}.json", attempt, replace_existing=False)
    return attempt
