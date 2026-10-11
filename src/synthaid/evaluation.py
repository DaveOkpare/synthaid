"""Checking an agent's draft: the result, and an LLM judge."""

from collections.abc import Callable, Mapping, Sequence
import dataclasses
import enum
import json
from typing import Any, Self, TypeAlias

import pydantic

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
You are a strict judge. You will be shown a list of criteria, the \
instruction and conversation of the current step when there are any, and \
one draft reply written by an assistant. Use the conversation, including \
tool results, to check the draft. Decide, for each criterion, whether the \
draft meets it: `met` is "yes" only when the draft clearly has what the \
criterion describes, "no" when it does not, and "n/a" when the criterion \
does not apply to this draft. Some criteria describe things that should \
not be there; judge them the same way, `met` is "yes" when the thing is \
present.

Answer every criterion exactly once, in the order given, copying its \
content exactly. Then \
write `feedback` for the assistant: say what to fix, specifically and \
briefly. If nothing needs fixing, say so."""


def _drop_description(schema: dict[str, Any]) -> None:
    """Removes the class docstring that Pydantic puts in the schema."""
    schema.pop("description", None)


class Met(enum.StrEnum):
    """The judge's answer for one criterion."""

    YES = "yes"
    NO = "no"
    NA = "n/a"


class Criterion(pydantic.BaseModel):
    """One thing the judge looks for in a draft, and the judge's answer.

    You create a Criterion with `content` and `weight`. The judge never
    sees this class: it gets the contents and replies with an Answer for
    each, and an LLMJudge then fills in `met` here.

    `content` describes the thing itself, whether it is good or bad. The
    sign of `weight` says which: positive for something the draft should
    have, negative for something it should not have.

    A YES answer adds `weight` to the score. NO and NA add 0, and an NA
    criterion is also left out of an LLMJudge's default threshold.

    Attributes:
        content: What the judge looks for, written for the judge. Unique
            among a judge's criteria.
        weight: What the criterion adds to the weighted score when it is
            met. Never sent to the model.
        met: The judge's answer. None until the judge answers. For a
            negative criterion, YES means the unwanted thing is present.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    content: str
    weight: float = 1.0
    met: Met | None = None


class Answer(pydantic.BaseModel):
    """The judge's answer for one criterion, as the model writes it.

    Attributes:
        content: The criterion's content, copied exactly.
        met: Whether the draft has what `content` describes.
    """

    model_config = pydantic.ConfigDict(json_schema_extra=_drop_description)

    content: str = pydantic.Field(description="The criterion, copied exactly.")
    met: Met = pydantic.Field(
        description="Whether the draft has what the criterion describes, or "
        "n/a when the criterion does not apply."
    )


class Verdict(pydantic.BaseModel):
    """The judge's output for one draft. The output type of an LLMJudge.

    It holds only what the model wrote, so it never has weights.
    Validating with `context={"criteria": criteria}` checks that there is
    one answer per criterion, in the same order, with the content copied
    exactly. Without that context, any answers are accepted.

    Attributes:
        answers: One answer per criterion, in order.
        feedback: What to fix, written for the agent.
    """

    model_config = pydantic.ConfigDict(json_schema_extra=_drop_description)

    answers: list[Answer] = pydantic.Field(
        description="One answer per criterion, in the order given."
    )
    feedback: str = pydantic.Field(
        description="What the assistant should fix, or that nothing needs "
        "fixing."
    )

    @pydantic.model_validator(mode="after")
    def _check_answers(self, info: pydantic.ValidationInfo) -> Self:
        """Checks the answers against the criteria in the context.

        Raises:
            ValueError: The answers are not one per criterion, in order,
                with the content copied exactly.
        """
        if not info.context or "criteria" not in info.context:
            return self
        criteria: Sequence[Criterion] = info.context["criteria"]
        expected = [item.content for item in criteria]
        answered = [item.content for item in self.answers]
        if answered != expected:
            raise ValueError(
                f"Answer each criterion once, in order: {answered=}"
            )
        return self


Passes: TypeAlias = Callable[[Sequence[Criterion], float], bool]
"""Decides from the answered criteria and a threshold whether a draft passes."""


def _weighted_score_passes(
    criteria: Sequence[Criterion], threshold: float
) -> bool:
    """Returns whether the weights of the met criteria reach `threshold`.

    The default Passes of an LLMJudge. A met negative criterion lowers
    the score. An unmet or NA criterion adds 0.

    Args:
        criteria: The criteria with `met` filled in.
        threshold: The lowest weighted score that passes.

    Returns:
        True when the weighted score is at least `threshold`.
    """
    score = sum(item.weight for item in criteria if item.met == Met.YES)
    return score >= threshold


class LLMJudge(agent.Agent):
    """An Agent that judges drafts against its criteria.

    An LLMJudge is an evaluator for `agent.Agent`: pass it as
    `Agent(..., evaluator=LLMJudge(...))`. A code eval is any other
    function that takes an `agent.Draft` and returns an `EvalResult`.

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
            criteria: What the judge checks, in order. Contents must be
                unique and there must be at least one.
            instructions: The judge's system message. Defaults to a strict
                judge prompt.
            passes: Decides from the answered criteria and `threshold`
                whether the draft passes. None compares the weighted score
                with `threshold`.
            threshold: Passed to `passes`. None means the sum of the
                positive weights of the criteria that are not NA, worked
                out for each verdict. So by default a draft passes only
                when every applicable positive criterion is met and no
                negative one is.

        Raises:
            ValueError: `criteria` is empty or two criteria share a
                content.
        """
        if not criteria:
            raise ValueError("A judge needs at least one criterion")
        contents = [item.content for item in criteria]
        duplicates = sorted(
            {content for content in contents if contents.count(content) > 1}
        )
        if duplicates:
            raise ValueError(f"Duplicate criterion contents: {duplicates}")
        if passes is None:
            passes = _weighted_score_passes
        super().__init__(
            model, instructions, output_type=Verdict, max_iterations=1
        )
        self.criteria = tuple(criteria)
        self._passes = passes
        self._threshold = threshold

    def __call__(self, draft: agent.Draft) -> EvalResult:
        """Judges one draft in the context of its step.

        Sends one user message through `run()` with these sections: the
        criteria as JSON, the step instruction when there is one, the
        step's conversation when it is not empty, and the draft. Messages
        are shown as their content (JSON when structured) and their tool
        calls. Reasoning is never shown.

        Args:
            draft: The assistant Message to judge, with its context.

        Returns:
            An EvalResult with the verdict's feedback and `passed` from
            `passes`. `metadata["verdict"]` is the Verdict as the model
            wrote it, and `metadata["criteria"]` is our criteria, in
            order and with their weights, with `met` from the answers.

        Raises:
            pydantic.ValidationError: The reply was not a Verdict, or did
                not answer each criterion once, in order.
            openai.APIError: Any transport or server error.
        """
        prompt = message.Message("user", self._prompt(draft))
        reply = self.run([prompt])[-1]
        verdict = Verdict.model_validate(
            reply.content, context={"criteria": self.criteria}
        )
        criteria = [
            item.model_copy(update={"met": answer.met})
            for item, answer in zip(self.criteria, verdict.answers, strict=True)
        ]
        threshold = self._threshold
        if threshold is None:
            threshold = sum(
                item.weight
                for item in criteria
                if item.weight > 0 and item.met != Met.NA
            )
        return EvalResult(
            verdict.feedback,
            passed=self._passes(criteria, threshold),
            metadata={"verdict": verdict, "criteria": criteria},
        )

    def _prompt(self, draft: agent.Draft) -> str:
        """Returns the user message for the judge, in "Heading:" sections.

        The criteria are a JSON list of their contents, in order, so the
        model can copy each one exactly into its answer.
        """
        criteria = [item.content for item in self.criteria]
        sections = [
            "Criteria:\n" + json.dumps(criteria, indent=2, ensure_ascii=False)
        ]
        if draft.instruction is not None:
            sections.append(f"Step instruction:\n{draft.instruction}")
        if draft.context:
            conversation = "\n".join(_line(item) for item in draft.context)
            sections.append(f"Conversation in this step:\n{conversation}")
        lines = [draft.message.text]
        lines += [
            f"Tool call: {call.name}({json.dumps(call.arguments)})"
            for call in draft.message.tool_calls
        ]
        sections.append("Draft:\n" + "\n".join(lines))
        return "\n\n".join(sections)


def _line(item: message.Message) -> str:
    """Returns one context message as a line, without its reasoning."""
    if not item.tool_calls:
        return f"[{item.role}] {item.text}"
    calls = ", ".join(
        f"{call.name}({json.dumps(call.arguments)})" for call in item.tool_calls
    )
    return f"[{item.role}] calls {calls}"
