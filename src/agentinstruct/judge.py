"""Evaluate criteria with a model or code and apply a weighted threshold."""

import inspect
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, StrictBool


@dataclass
class Criterion:
    context: str
    weight: float = 1.0


@dataclass
class Rubric:
    criteria: list[Criterion]
    threshold: float


@dataclass
class Judgment:
    passed: bool
    feedback: str = ""
    score: float | None = None


class Evaluator(Protocol):
    async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment: ...


class _Assessment(BaseModel):
    criteria: list[StrictBool]
    feedback: str


@dataclass
class Judge:
    rubric: Rubric
    model: str | None = None
    client: Any = None
    check: Callable[[Sequence[Mapping[str, Any]]], Any] | None = None
    prompt: str = (
        "Evaluate the supplied conversation against every criterion. "
        "Return exactly one Boolean per criterion in the original order: "
        "true if it passes, false if it fails. "
        "Include failed criteria; never omit them. "
        "Provide concise feedback explaining failures."
    )

    async def evaluate(self, messages: Sequence[Mapping[str, Any]]) -> Judgment:
        if self.check is None:
            assessment = await self._model_assessment(messages)
        else:
            value = self.check(messages)
            value = await value if inspect.isawaitable(value) else value
            assessment = _Assessment.model_validate({"feedback": "", **value})
        weights = [c.weight for c in self.rubric.criteria]
        score = sum(
            w * p for w, p in zip(weights, assessment.criteria, strict=True)
        ) / sum(weights)
        return Judgment(score > self.rubric.threshold, assessment.feedback, score)

    async def _model_assessment(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> _Assessment:
        criteria = [c.context for c in self.rubric.criteria]
        response = await self.client.responses.parse(
            model=self.model,
            store=False,
            instructions=self.prompt,
            input=json.dumps({"criteria": criteria, "messages": messages}),
            text_format=_Assessment,
        )
        assessment: _Assessment | None = response.output_parsed
        if assessment is None or response.status != "completed":
            raise ValueError("Judge did not return a completed assessment")
        return assessment
