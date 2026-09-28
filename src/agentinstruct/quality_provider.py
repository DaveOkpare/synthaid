"""Shared typed model judgment without owning acceptance or Trace persistence."""

import asyncio
from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from agentinstruct.plans import (
    ModelPlan,
    ProviderPlan,
    StructuredOutputPlan,
    canonical_json,
)
from agentinstruct.provider_errors import ProviderError, StructuredOutputValidationError
from agentinstruct.providers import (
    InferenceControls,
    Provider,
    ProviderRequest,
    response_evidence,
)
from agentinstruct.quality import Rubric, score_verdicts
from agentinstruct.store import timestamp
from agentinstruct.structured import compile_structured_output
from agentinstruct.traces import Event, Message, immutable_data


class CriterionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    id: str
    passed: bool


class QualityDecision(BaseModel):
    """List preserves duplicate IDs and supports any active step Rubric."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    criteria: list[CriterionVerdict]
    feedback: str


def quality_request(model: ModelPlan, schema: StructuredOutputPlan) -> ProviderRequest:
    """The same request contract is used in model-free capability preflight."""
    if compile_structured_output(QualityDecision) != schema:
        raise StructuredOutputValidationError("unsupported_schema")
    return ProviderRequest(
        model.name,
        (Message("system", "Evaluate quality."),),
        structured_output=QualityDecision,
        reasoning=model.reasoning,
    )


class QualityCall:
    def __init__(
        self,
        model: ModelPlan,
        schema: StructuredOutputPlan,
        provider_plan: ProviderPlan,
        provider: Provider,
        record: Callable[[Event], None],
        purpose: str,
    ) -> None:
        self.model, self.schema = model, schema
        self.provider_plan, self.provider = provider_plan, provider
        self.record, self.purpose = record, purpose
        quality_request(model, schema)

    async def evaluate(
        self,
        instruction: str,
        payload: object,
        rubric: Rubric,
        *,
        actor_id: str | None = None,
        turn_id: str | None = None,
        step_id: str | None = None,
    ) -> QualityDecision:
        identity = {
            "purpose": self.purpose,
            "provider": self.provider_plan.id,
            "api": self.provider_plan.api,
            "requested_model": self.model.name,
            "schema_fingerprint": self.schema.fingerprint,
        }
        request = ProviderRequest(
            self.model.name,
            (
                Message(
                    "system",
                    instruction
                    + "\nReturn one Boolean verdict per active Criterion ID "
                    "and text feedback.",
                ),
                Message("user", canonical_json(payload)),
            ),
            inference=InferenceControls(self.model.temperature, self.model.max_tokens),
            structured_output=QualityDecision,
            reasoning=self.model.reasoning,
            vllm_options=self.provider_plan.vllm_options,
            metadata={"actor_id": actor_id, "turn_id": turn_id, "step_id": step_id},
        )
        response = None
        try:
            response = await self.provider.generate(request)
            if response.refused:
                raise ProviderError("refusal", request_id=response.request_id)
            if response.finish_state in {"length", "content_filter"}:
                raise ProviderError("incomplete", request_id=response.request_id)
            if response.message.tool_calls:
                raise StructuredOutputValidationError("schema_mismatch")
            decision = response.parsed
            if not isinstance(decision, QualityDecision):
                raise StructuredOutputValidationError("schema_mismatch")
            try:
                score_verdicts(
                    rubric, [(item.id, item.passed) for item in decision.criteria]
                )
            except ValueError:
                raise StructuredOutputValidationError("schema_mismatch") from None
        except (ProviderError, asyncio.CancelledError) as exc:
            self.record(
                Event(
                    uuid4().hex,
                    "model_call",
                    timestamp(),
                    immutable_data(
                        {
                            **identity,
                            **(
                                response_evidence(
                                    response,
                                    request,
                                    retain=self.provider_plan.retain_reasoning,
                                )
                                if response is not None
                                else {}
                            ),
                            "error": {"kind": exc.kind, **exc.metadata}
                            if isinstance(exc, ProviderError)
                            else {"kind": "timeout"},
                        }
                    ),
                    actor_id,
                    turn_id,
                    step_id,
                )
            )
            raise
        self.record(
            Event(
                uuid4().hex,
                "model_call",
                timestamp(),
                immutable_data(
                    {
                        **identity,
                        **response_evidence(
                            response,
                            request,
                            retain=self.provider_plan.retain_reasoning,
                        ),
                        "result": decision.model_dump(mode="json", by_alias=True),
                    }
                ),
                actor_id,
                turn_id,
                step_id,
            )
        )
        return decision
