"""One reusable evaluator for private message review and final verification."""

import asyncio
import inspect
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Protocol, runtime_checkable

from agentinstruct.episode import Message


@dataclass(frozen=True)
class Criterion:
    id: str
    weight: float = 1.0
    description: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", self.id):
            raise ValueError("Criterion requires a portable identifier")
        if (
            isinstance(self.weight, bool)
            or not math.isfinite(self.weight)
            or self.weight <= 0
        ):
            raise ValueError("Criterion weight must be finite and positive")


@dataclass(frozen=True)
class Rubric:
    criteria: tuple[Criterion, ...]
    threshold: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "criteria", tuple(self.criteria))
        ids = [item.id.casefold() for item in self.criteria]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("Rubric requires nonempty unique criteria")
        total = _weight_total(self.criteria)
        if not math.isfinite(total) or isinstance(self.threshold, bool):
            raise ValueError("Rubric weights and threshold must be finite")
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("Rubric threshold must be between zero and one")


@dataclass(frozen=True)
class Judgment:
    passed: bool
    feedback: str = ""
    criteria: Mapping[str, bool] = field(default_factory=dict)
    score: float | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.passed) is not bool or not isinstance(self.feedback, str):
            raise ValueError("Judgment needs a Boolean verdict and text feedback")
        if self.score is not None and (
            isinstance(self.score, bool)
            or not math.isfinite(self.score)
            or not 0 <= self.score <= 1
        ):
            raise ValueError("Judgment score must be finite and between zero and one")
        if any(
            not isinstance(key, str) or type(value) is not bool
            for key, value in self.criteria.items()
        ):
            raise ValueError("Criterion verdicts must be actual Booleans")
        object.__setattr__(self, "criteria", dict(self.criteria))
        object.__setattr__(self, "evidence", deepcopy(dict(self.evidence)))


class JudgeError(RuntimeError):
    def __init__(self, kind: str, evidence: Mapping[str, Any] | None = None) -> None:
        self.kind, self.evidence = kind, deepcopy(dict(evidence or {}))
        super().__init__(f"Judge {kind} failed")


@runtime_checkable
class Evaluator(Protocol):
    async def evaluate(self, messages: Sequence[Message]) -> Judgment: ...


@dataclass(frozen=True)
class Judge:
    client: Any = field(default=None, repr=False, compare=False)
    model: str | None = None
    prompt: str = ""
    rubric: Rubric | None = None
    check: Callable[[Sequence[Message]], Any] | None = field(default=None, repr=False)
    api: str = "chat_completions"
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.check is not None:
            if (
                not callable(self.check)
                or self.model is not None
                or self.client is not None
                or self.prompt
            ):
                raise ValueError(
                    "Choose callable check or client/model/prompt evaluation"
                )
        elif self.client is None or not self.model or not self.prompt:
            raise ValueError("Model Judge needs client, model and prompt")
        _judge_settings(self)

    async def evaluate(self, messages: Sequence[Message]) -> Judgment:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                if self.check is not None:
                    value = self.check(tuple(messages))
                    value = await value if inspect.isawaitable(value) else value
                    evidence = value.evidence if isinstance(value, Judgment) else {}
                    result = _judgment(value, self.rubric)
                    return replace(result, evidence=evidence)
                return await self._model_judgment(tuple(messages))
        except JudgeError:
            raise
        except Exception as exc:
            kind = (
                "malformed" if isinstance(exc, (ValueError, TypeError)) else "execution"
            )
            if isinstance(exc, TimeoutError):
                kind = "timeout"
            raise JudgeError(kind, getattr(exc, "evidence", {})) from exc

    async def _model_judgment(self, messages: tuple[Message, ...]) -> Judgment:
        history = [
            {"role": "system", "content": self.prompt},
            {
                "role": "user",
                "content": json.dumps(messages, default=asdict, allow_nan=False),
            },
        ]
        format_ = {
            "name": "Judgment",
            "schema": _judgment_schema(self.rubric),
            "strict": True,
        }
        client = self.client.with_options(max_retries=0)
        if self.api == "responses":
            response = await client.responses.create(
                model=self.model,
                input=history,
                store=False,
                text={"format": {"type": "json_schema", **format_}},
            )
            if response.status != "completed" or response.error:
                raise ValueError("Judge response did not complete")
            content = response.output_text
        else:
            response = await client.chat.completions.create(
                model=self.model,
                messages=history,
                store=False,
                response_format={"type": "json_schema", "json_schema": format_},
            )
            choice = response.choices[0]
            if choice.message.refusal or choice.finish_reason != "stop":
                raise ValueError("Judge response did not complete")
            content = choice.message.content or ""
        return _judgment(json.loads(content), self.rubric)


def _verdicts(value: Any) -> dict[str, bool]:
    items = value.items() if isinstance(value, Mapping) else value
    result: dict[str, bool] = {}
    for key, passed in items:
        if key in result or not isinstance(key, str) or type(passed) is not bool:
            raise ValueError("Verdicts need unique IDs and actual Booleans")
        result[key] = passed
    return result


def _judgment(value: Any, rubric: Rubric | None) -> Judgment:
    if isinstance(value, Judgment):
        value = {
            "passed": value.passed,
            "criteria": value.criteria,
            "feedback": value.feedback,
        }
    if type(value) is bool:
        value = {"passed": value, "feedback": ""}
    if not isinstance(value, Mapping) or not isinstance(value.get("feedback", ""), str):
        raise ValueError("Judge must return a judgment with text feedback")
    criteria = _verdicts(value.get("criteria", {}))
    feedback = value.get("feedback", "")
    if rubric is not None:
        score = _score(rubric, criteria)
        return Judgment(score >= rubric.threshold, feedback, criteria, score)
    if type(value.get("passed")) is not bool or criteria:
        raise ValueError("Without a Rubric, Judge must return a Boolean passed verdict")
    return Judgment(value["passed"], feedback, score=float(value["passed"]))


def _score(rubric: Rubric, criteria: Mapping[str, bool]) -> float:
    if set(criteria) != {item.id for item in rubric.criteria}:
        raise ValueError("Verdicts must match every Criterion exactly")
    return math.fsum(
        item.weight for item in rubric.criteria if criteria[item.id]
    ) / math.fsum(item.weight for item in rubric.criteria)


def _judgment_schema(rubric: Rubric | None) -> dict[str, Any]:
    if rubric is None:
        properties = {"passed": {"type": "boolean"}}
    else:
        verdicts = {item.id: {"type": "boolean"} for item in rubric.criteria}
        properties = {"criteria": _strict_object(verdicts)}
    return _strict_object({**properties, "feedback": {"type": "string"}})


def _weight_total(criteria: Sequence[Criterion]) -> float:
    try:
        return math.fsum(item.weight for item in criteria)
    except OverflowError as exc:
        raise ValueError("Rubric weights must have a finite total") from exc


def _strict_object(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


def _judge_settings(judge: Judge) -> None:
    if not isinstance(judge.prompt, str) or (
        judge.model is not None and not isinstance(judge.model, str)
    ):
        raise ValueError("Judge model and prompt must be text")
    if judge.api not in {"chat_completions", "responses"}:
        raise ValueError("Unsupported Judge API")
    if judge.rubric is not None and not isinstance(judge.rubric, Rubric):
        raise ValueError("Judge rubric must be a Rubric")
    if judge.timeout_seconds is not None and (
        isinstance(judge.timeout_seconds, bool)
        or not math.isfinite(judge.timeout_seconds)
        or judge.timeout_seconds <= 0
    ):
        raise ValueError("Judge timeout must be finite and positive")
