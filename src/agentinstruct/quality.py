"""Weighted Boolean scoring shared by independent Review and Verification loops."""

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agentinstruct.paths import portable_name


@dataclass(frozen=True)
class Criterion:
    id: str
    weight: float = 1.0
    description: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", self.id):
            raise ValueError("Criterion requires a portable identifier")
        portable_name(self.id)
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
        ids = [criterion.id.casefold() for criterion in self.criteria]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Rubric requires nonempty, uniquely identified Criteria")
        try:
            total = math.fsum(criterion.weight for criterion in self.criteria)
        except OverflowError as exc:
            raise ValueError("Rubric total weight must be finite and positive") from exc
        if not math.isfinite(total) or total <= 0:
            raise ValueError("Rubric total weight must be finite and positive")
        if (
            isinstance(self.threshold, bool)
            or not math.isfinite(self.threshold)
            or not 0 <= self.threshold <= 1
        ):
            raise ValueError("Rubric threshold must be finite and between zero and one")


type Verdicts = Mapping[str, bool] | Sequence[tuple[str, bool]]


def score_verdicts(rubric: Rubric, verdicts: Verdicts) -> float:
    """Validate complete, exact Boolean evidence before deriving its score."""
    if not isinstance(verdicts, (Mapping, Sequence)) or isinstance(verdicts, str):
        raise ValueError("Verdicts must be a mapping or a sequence of ID/Boolean pairs")
    items = verdicts.items() if isinstance(verdicts, Mapping) else verdicts
    evidence: dict[str, bool] = {}
    for identifier, verdict in items:
        if not isinstance(identifier, str) or type(verdict) is not bool:
            raise ValueError(
                "Criterion verdicts require string IDs and actual Booleans"
            )
        if identifier in evidence:
            raise ValueError(f"Duplicate Criterion verdict: {identifier}")
        evidence[identifier] = verdict
    if set(evidence) != {criterion.id for criterion in rubric.criteria}:
        raise ValueError("Verdicts must contain every declared Criterion and no others")
    passing = math.fsum(
        criterion.weight for criterion in rubric.criteria if evidence[criterion.id]
    )
    return passing / math.fsum(criterion.weight for criterion in rubric.criteria)
