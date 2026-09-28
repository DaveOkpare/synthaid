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

from pydantic import TypeAdapter, ValidationError

from agentinstruct.components import validate_component
from agentinstruct.failures import SafeDiagnostics, complete_cleanup
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
    _sync_directory,
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
    immutable_data,
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
        try:
            plan = TypeAdapter(VerifierPlan).validate_json(canonical_json(stored_plan))
        except ValidationError:
            raise ValueError("Persisted Verifier Plan is invalid") from None
    started_at, started = timestamp(), monotonic()
    provenance = ComponentProvenance("verifier", plan.type, None)
    status: Literal["accepted", "rejected", "unverified"] = "unverified"
    score = None
    criteria: dict[str, bool] = {}
    feedback = ""
    error = None
    stage: Literal["execution", "malformed", "timeout", "cancelled"] = "execution"
    deadline = asyncio.timeout(plan.timeout_seconds)
    provider = None
    verifier: Verifier
    events: list[Event] = []
    stored_providers = trace.run_plan.get("providers", {})
    try:
        diagnostics = SafeDiagnostics(
            (provider_plan,)
            if provider_plan is not None
            else (
                TypeAdapter(ProviderPlan).validate_json(canonical_json(item))
                for item in stored_providers.values()
            )
            if isinstance(stored_providers, Mapping)
            else ()
        )
    except ValidationError:
        raise ValueError("Persisted Provider Plan is invalid") from None

    def record_event(event: Event) -> None:
        events.append(
            TypeAdapter(Event).validate_python(diagnostics.data(event, diagnostic=True))
        )

    def failure(
        exc: BaseException,
        kind: Literal["execution", "malformed", "timeout", "cancelled"],
        *,
        lifecycle: str = "verifier",
    ) -> VerificationError:
        evidence = diagnostics.failure(exc, lifecycle, kind=kind)
        record_event(
            Event(uuid4().hex, "verifier_error", timestamp(), immutable_data(evidence))
        )
        causes = evidence["causes"]
        assert isinstance(causes, list)
        return VerificationError(
            kind,
            type(exc).__name__,
            str(evidence["message"]),
            exc.kind if isinstance(exc, ProviderError) else None,
            tuple(cast(Mapping[str, FrozenJsonValue], cause) for cause in causes),
            lifecycle,
        )

    cancelled: asyncio.CancelledError | None = None
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
                        record_event,
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
        feedback = diagnostics.diagnostic_text(result.feedback)
        status = "accepted" if score >= plan.rubric.threshold else "rejected"
    except asyncio.CancelledError as exc:
        cancelled = exc
        error = failure(exc, "cancelled")
    except Exception as exc:
        score, criteria, feedback = None, {}, ""
        if isinstance(exc, TimeoutError) and deadline.expired():
            stage = "timeout"
        if isinstance(exc, ProviderError) and exc.kind in {
            "invalid_json",
            "schema_mismatch",
        }:
            stage = "malformed"
        error = failure(exc, stage)
    finally:

        async def cleanup() -> None:
            nonlocal score, criteria, feedback, status, error
            if provider is not None:
                try:
                    async with asyncio.timeout(plan.timeout_seconds):
                        await provider.aclose()
                except (Exception, asyncio.CancelledError) as exc:
                    score, criteria, feedback, status = None, {}, "", "unverified"
                    error = failure(exc, "execution", lifecycle="provider_cleanup")

        if await complete_cleanup(cleanup()):
            cancelled = asyncio.CancelledError()
            score, criteria, feedback, status = None, {}, "", "unverified"
            error = failure(cancelled, "cancelled", lifecycle="cleanup")
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
    attempt = TypeAdapter(VerificationAttempt).validate_json(
        canonical_json(diagnostics.data(attempt))
    )
    attempts = verification_directory(path)
    try:
        attempts.mkdir(exist_ok=True)
        _sync_directory(attempts.parent)
        write_json(attempts / f"{attempt.id}.json", attempt, replace_existing=False)
    except OSError:
        if cancelled is not None:
            raise cancelled from None
        raise
    if cancelled is not None:
        raise cancelled
    return attempt
