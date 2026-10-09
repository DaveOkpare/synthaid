"""Results of checking an agent's draft."""

from collections.abc import Mapping
import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class EvalResult:
    """What an evaluator says about one draft.

    Attributes:
        feedback: What to fix, sent back to the model when the draft fails.
        score: The aggregated score.
        passed: Whether the draft is accepted.
        metadata: Anything else the evaluator wants to keep, such as which
            criteria were met.
    """

    feedback: str
    _: dataclasses.KW_ONLY
    score: float
    passed: bool
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)
