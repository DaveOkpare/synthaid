"""Post-generation Verification over sealed immutable Trace snapshots."""

import asyncio
import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import TypeAdapter

from agentinstruct.plans import VerifierPlan, canonical_json
from agentinstruct.quality import Verdicts, score_verdicts
from agentinstruct.store import (
    load_trace,
    timestamp,
    verification_directory,
    write_json,
)
from agentinstruct.traces import (
    ComponentProvenance,
    TraceSnapshot,
    VerificationAttempt,
    VerificationError,
)


def component_provenance(kind: str, component: object) -> ComponentProvenance:
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
    return ComponentProvenance(kind, f"{cls.__module__}:{cls.__qualname__}", digest)


@dataclass(frozen=True)
class VerificationResult:
    criteria: Verdicts
    feedback: str = ""


class Verifier(Protocol):
    async def verify(self, trace: TraceSnapshot) -> VerificationResult: ...


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
    if plan.type == "deterministic":
        return DeterministicVerifier(plan)
    raise ValueError("custom Verifier requires a verifier_factory")


async def reverify(
    path: str | Path,
    *,
    plan: VerifierPlan | None = None,
    verifier_factory: Callable[[VerifierPlan], Verifier] = create_verifier,
) -> VerificationAttempt:
    """Append a quality decision without changing any sealed generation files."""
    trace = load_trace(path)
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
    try:
        verifier = verifier_factory(plan)
        provenance = component_provenance("verifier", verifier)
        async with deadline:
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
        error = VerificationError(stage, type(exc).__name__, str(exc))
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
    )
    attempts = verification_directory(path)
    attempts.mkdir(exist_ok=True)
    write_json(attempts / f"{attempt.id}.json", attempt, replace_existing=False)
    return attempt
