"""Per-Message Review contracts, independent of post-generation Verification."""

from dataclasses import dataclass
from typing import Literal, Protocol

from agentinstruct.plans import ReviewerPlan
from agentinstruct.quality import Rubric, Verdicts
from agentinstruct.quality_provider import QualityCall
from agentinstruct.traces import Message


@dataclass(frozen=True)
class ReviewRequest:
    instruction: str
    rubric: Rubric
    message: Message
    messages: tuple[Message, ...]
    agent_instruction: str
    step_id: str | None = None
    actor_id: str | None = None
    turn_id: str | None = None


@dataclass(frozen=True)
class ReviewResult:
    criteria: Verdicts
    feedback: str = ""


class Reviewer(Protocol):
    async def review(self, request: ReviewRequest) -> ReviewResult: ...


class ModelReviewer:
    def __init__(self, call: QualityCall) -> None:
        self.call = call

    async def review(self, request: ReviewRequest) -> ReviewResult:
        decision = await self.call.evaluate(
            request.instruction,
            {
                "rubric": request.rubric,
                "proposal": request.message,
                "accepted_messages": request.messages,
                "agent_instruction": request.agent_instruction,
            },
            request.rubric,
            actor_id=request.actor_id,
            turn_id=request.turn_id,
            step_id=request.step_id,
        )
        return ReviewResult(
            [(item.id, item.passed) for item in decision.criteria], decision.feedback
        )


class ReviewExhausted(RuntimeError):
    """A proposal used every permitted revision without passing Review."""


class ReviewError(RuntimeError):
    """A failed Review operation, distinct from a valid rejection."""

    def __init__(self, kind: Literal["execution", "malformed"]) -> None:
        self.kind = kind
        super().__init__(f"Reviewer {kind} failure")


class DeterministicReviewer:
    """Declared structural checks for offline Tasks; no semantic quality claims."""

    def __init__(self, plan: ReviewerPlan) -> None:
        self.plan = plan

    async def review(self, request: ReviewRequest) -> ReviewResult:
        nonempty = bool(request.message.content.strip())
        return ReviewResult(
            {criterion.id: nonempty for criterion in request.rubric.criteria},
            "" if nonempty else "Provide nonempty message content.",
        )


def create_reviewer(plan: ReviewerPlan) -> Reviewer:
    if plan.type == "deterministic":
        return DeterministicReviewer(plan)
    raise ValueError("custom Reviewer requires a reviewer_factory")
