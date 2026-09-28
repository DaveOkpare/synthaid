"""Observation projection and trace evidence for Provider-backed participants."""

from collections.abc import Callable
from dataclasses import replace
from typing import Literal
from uuid import uuid4

from agentinstruct.execution import Observation
from agentinstruct.plans import AgentPlan, ProviderPlan
from agentinstruct.providers import (
    InferenceControls,
    Provider,
    ProviderError,
    ProviderRequest,
    ReasoningContinuation,
    ReasoningItem,
    response_evidence,
)
from agentinstruct.store import timestamp
from agentinstruct.traces import Event, Message, immutable_data


class ModelAgent:
    def __init__(
        self,
        plan: AgentPlan,
        provider_plan: ProviderPlan,
        provider: Provider,
        *,
        record_event: Callable[[Event], None],
        run_id: str,
        trace_id: str,
    ) -> None:
        self._plan = plan
        self._provider_plan = provider_plan
        self._provider = provider
        self._record = record_event
        self._run_id = run_id
        self._trace_id = trace_id
        self._pending_reasoning: (
            tuple[Message, tuple[ReasoningItem, ...], frozenset[str]] | None
        ) = None
        self._accepted_reasoning: dict[str, tuple[ReasoningItem, ...]] = {}

    async def generate(self, observation: Observation) -> Message:
        history = [Message("system", observation.instruction)]
        for message in observation.messages:
            role: Literal["tool", "assistant", "user"] = (
                "tool"
                if message.role == "tool"
                else "assistant"
                if message.actor_id == observation.actor_id
                else "user"
            )
            history.append(replace(message, role=role))
        # A returned proposal is not accepted until it appears in this actor's
        # authoritative Observation. Message IDs are assigned by Interaction.
        if self._pending_reasoning is not None:
            proposal, items, prior_message_ids = self._pending_reasoning
            for message in history:
                if (
                    message.role == "assistant"
                    and message.id not in prior_message_ids
                    and message.tool_calls
                    and message.tool_calls == proposal.tool_calls
                    and message.content == proposal.content
                ):
                    self._accepted_reasoning[message.tool_calls[0].id] = items
            self._pending_reasoning = None
        continuations = tuple(
            ReasoningContinuation(
                message, self._accepted_reasoning[message.tool_calls[0].id]
            )
            for message in history
            if message.role == "assistant"
            and message.tool_calls
            and message.tool_calls[0].id in self._accepted_reasoning
        )
        if observation.review_feedback is not None:
            history.append(
                Message(
                    "user",
                    "Private review feedback for your next proposal:\n"
                    + observation.review_feedback,
                )
            )
        request = ProviderRequest(
            self._plan.model.name,
            tuple(history),
            observation.tools,
            tool_choice="auto" if observation.tools else None,
            inference=InferenceControls(
                self._plan.model.temperature, self._plan.model.max_tokens
            ),
            reasoning=self._plan.model.reasoning,
            continuations=continuations,
            metadata={
                "run_id": self._run_id,
                "trace_id": self._trace_id,
                "actor_id": observation.actor_id,
                "step_id": observation.step_id,
                "turn_id": observation.turn_id,
            },
        )
        identity = {
            "provider": self._provider_plan.id,
            "api": self._provider_plan.api,
            "requested_model": request.model,
        }
        try:
            response = await self._provider.generate(request)
        except ProviderError as exc:
            self._record(
                Event(
                    uuid4().hex,
                    "model_call",
                    timestamp(),
                    {**identity, "error": {"kind": exc.kind, **exc.metadata}},
                    observation.actor_id,
                    observation.turn_id,
                    observation.step_id,
                )
            )
            raise
        self._record(
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
                            retain=self._provider_plan.retain_reasoning,
                        ),
                    }
                ),
                observation.actor_id,
                observation.turn_id,
                observation.step_id,
            )
        )
        if response.refused:
            raise ProviderError("refusal", request_id=response.request_id)
        if response.finish_state in {"length", "content_filter"}:
            raise ProviderError("incomplete", request_id=response.request_id)
        if response.message.tool_calls and response.reasoning:
            self._pending_reasoning = (
                response.message,
                response.reasoning,
                frozenset(message.id for message in observation.messages),
            )
        return response.message
