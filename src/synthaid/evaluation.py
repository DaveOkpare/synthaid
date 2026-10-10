"""Checking an agent's draft: the result, and an LLM judge."""

from collections.abc import Callable, Mapping, Sequence
import dataclasses
import json
from typing import Any, Self, TypeAlias

import pydantic
from pydantic import json_schema

from synthaid import agent
from synthaid import message
from synthaid import model


@dataclasses.dataclass(frozen=True)
class EvalResult:
    """What an evaluator says about one draft.

    Attributes:
        feedback: What to fix, sent back to the model when the draft fails.
        passed: Whether the draft passes the evaluator.
        metadata: Anything else the evaluator wants to keep, such as which
            criteria were met.
    """

    feedback: str
    _: dataclasses.KW_ONLY
    passed: bool
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)


_INSTRUCTIONS = """\
You are a strict judge. You will be shown a list of criteria and one draft \
reply written by an assistant. Decide, for each criterion, whether the \
draft meets it: `met` is true only when the draft clearly has what the \
criterion describes. Some criteria describe things that should not be \
there; judge them the same way, `met` is true when the thing is present.

Answer every criterion exactly once, copying its title and content. Then \
write `feedback` for the assistant: say what to fix, specifically and \
briefly. If nothing needs fixing, say so."""


def _drop_description(schema: dict[str, Any]) -> None:
    """Removes the class docstring that Pydantic puts in the schema."""
    schema.pop("description", None)


class Criterion(pydantic.BaseModel):
    """One thing the judge looks for in a draft, and the judge's answer.

    You create a Criterion with `title`, `content` and `weight`. The judge
    returns it with `met` filled in. The schema sent to the model holds
    only `title`, `content` and `met`, so the model never sees `weight`,
    and `met` is required in its reply.

    `content` describes the thing itself, whether it is good or bad. The
    sign of `weight` says which: positive for something the draft should
    have, negative for something it should not have.

    Attributes:
        title: A short name, unique among a judge's criteria.
        content: What the judge looks for, written for the judge.
        weight: What the criterion adds to the weighted score when it is
            met. Never sent to the model.
        met: Whether the draft has what `content` describes. None until
            the judge answers. For a negative criterion, met means the
            unwanted thing is present.
    """

    model_config = pydantic.ConfigDict(
        frozen=True, json_schema_extra=_drop_description
    )

    title: str = pydantic.Field(description="The criterion's title.")
    content: str = pydantic.Field(description="What to look for.")
    weight: json_schema.SkipJsonSchema[float] = 1.0
    met: bool | json_schema.SkipJsonSchema[None] = pydantic.Field(
        default=None,
        description="Whether the draft has what `content` describes.",
    )


class Verdict(pydantic.BaseModel):
    """The judge's output for one draft. The output type of an LLMJudge.

    Validating with `context={"criteria": criteria}` checks the answers
    against those criteria: each one must be answered exactly once. The
    result holds those criteria, in their order and with their weights,
    with `met` taken from the answers. Without that context, any criteria
    are accepted as they are.

    Attributes:
        criteria: Every criterion, with `met` filled in.
        feedback: What to fix, written for the agent.
    """

    model_config = pydantic.ConfigDict(
        revalidate_instances="always", json_schema_extra=_drop_description
    )

    criteria: list[Criterion] = pydantic.Field(
        description="Every criterion, each answered once."
    )
    feedback: str = pydantic.Field(
        description="What the assistant should fix, or that nothing needs "
        "fixing."
    )

    @pydantic.model_validator(mode="after")
    def _answer_criteria(self, info: pydantic.ValidationInfo) -> Self:
        """Puts the answers onto the criteria from the validation context.

        Raises:
            ValueError: The answers do not cover each criterion exactly
                once.
        """
        if not info.context or "criteria" not in info.context:
            return self
        criteria: Sequence[Criterion] = info.context["criteria"]
        met = {item.title: item.met for item in self.criteria}
        expected = {item.title for item in criteria}
        if len(self.criteria) != len(criteria) or met.keys() != expected:
            titles = [item.title for item in self.criteria]
            raise ValueError(f"Answer each criterion once: {titles=}")
        self.criteria = [
            item.model_copy(update={"met": met[item.title]})
            for item in criteria
        ]
        return self


Passes: TypeAlias = Callable[[Sequence[Criterion], float], bool]
"""Decides from the answered criteria and a threshold whether a draft passes."""


def _weighted_score_passes(
    criteria: Sequence[Criterion], threshold: float
) -> bool:
    """Returns whether the weights of the met criteria reach `threshold`.

    The default Passes of an LLMJudge. A met negative criterion lowers
    the score, and an unmet criterion adds 0.

    Args:
        criteria: The criteria with `met` filled in.
        threshold: The lowest weighted score that passes.

    Returns:
        True when the weighted score is at least `threshold`.
    """
    return sum(item.weight for item in criteria if item.met) >= threshold


class LLMJudge(agent.Agent):
    """An Agent that judges drafts against its criteria.

    An LLMJudge is an evaluator for `agent.Agent`: pass it as
    `Agent(..., evaluator=LLMJudge(...))`. A code eval is any other
    function that takes a draft and returns an `EvalResult`.

    Its output type is Verdict. `passes` decides from the answered
    criteria and the threshold whether the draft passes. By default, a
    draft passes when the weights of its met criteria reach the
    threshold.

    It is also an Agent, so `run()` and `logs` work as usual, and `logs`
    keeps every draft it has judged. Like any Agent, give each
    conversation its own LLMJudge. It has no tools, no evaluator of its
    own, and `max_iterations` is 1.

    Attributes:
        criteria: What the judge checks, in order.
    """

    def __init__(
        self,
        model: model.Model,
        criteria: Sequence[Criterion],
        instructions: str = _INSTRUCTIONS,
        *,
        passes: Passes | None = None,
        threshold: float | None = None,
    ) -> None:
        """Checks the criteria and builds the Agent with Verdict as output.

        Args:
            model: The model that judges. It must support structured
                output.
            criteria: What the judge checks. Titles must be unique and
                there must be at least one.
            instructions: The judge's system message. Defaults to a strict
                judge prompt.
            passes: Decides from the answered criteria and `threshold`
                whether the draft passes. None compares the weighted score
                with `threshold`.
            threshold: Passed to `passes`. None means the sum of the
                positive weights, so by default a draft passes only when
                every positive criterion is met and no negative one is.

        Raises:
            ValueError: `criteria` is empty or two criteria share a title.
        """
        if not criteria:
            raise ValueError("A judge needs at least one criterion")
        titles = [item.title for item in criteria]
        duplicates = sorted(
            {title for title in titles if titles.count(title) > 1}
        )
        if duplicates:
            raise ValueError(f"Duplicate criterion titles: {duplicates}")
        if passes is None:
            passes = _weighted_score_passes
        if threshold is None:
            threshold = sum(item.weight for item in criteria if item.weight > 0)
        super().__init__(
            model, instructions, output_type=Verdict, max_iterations=1
        )
        self.criteria = tuple(criteria)
        self._passes = passes
        self._threshold = threshold

    def __call__(self, draft: message.Message) -> EvalResult:
        """Judges one draft.

        Sends one user message with the criteria and the draft, through
        `run()`. The draft is shown as its content (JSON when structured)
        followed by its tool calls. Its reasoning is left out. The judge
        never sees the conversation the draft came from.

        Args:
            draft: The assistant Message to judge.

        Returns:
            An EvalResult with the verdict's feedback, `passed` from
            `passes`, and `metadata["verdict"]`: the Verdict, with the
            criteria in order and with their weights.

        Raises:
            pydantic.ValidationError: The reply was not a Verdict, or did
                not answer each criterion exactly once.
            openai.APIError: Any transport or server error.
        """
        prompt = message.Message("user", self._prompt(draft))
        reply = self.run([prompt])[-1]
        verdict = Verdict.model_validate(
            reply.content, context={"criteria": self.criteria}
        )
        return EvalResult(
            verdict.feedback,
            passed=self._passes(verdict.criteria, self._threshold),
            metadata={"verdict": verdict},
        )

    def _prompt(self, draft: message.Message) -> str:
        """Returns the user message with the criteria and then the draft."""
        lines = ["Criteria:"]
        lines += [f"- {item.title}: {item.content}" for item in self.criteria]
        lines += ["", "Draft:", draft.text]
        lines += [
            f"Tool call: {call.name}({json.dumps(call.arguments)})"
            for call in draft.tool_calls
        ]
        return "\n".join(lines)
