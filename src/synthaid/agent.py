"""An agent that answers with a model, its tools and an optional evaluator."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import dataclasses
import typing

import pydantic

from synthaid import exception
from synthaid import message
from synthaid import model
from synthaid import tool

if typing.TYPE_CHECKING:
    # evaluation imports agent for LLMJudge.
    from synthaid import evaluation


@dataclasses.dataclass(eq=False)
class Agent:
    """A model with instructions, tools and an optional self-check.

    The whole interface is `run()` and `logs`.

    An Agent is not frozen because it records its own logs. One Agent
    serves one role in one conversation. Share the Model, not the Agent.

    Attributes:
        model: The Model to call. It can be shared with other agents.
        instructions: The system message sent before every request.
        output_type: str for text, or a Pydantic class for structured
            output. A Pydantic class cannot be combined with tools.
        tools: The tools the model may ask to run. Names must be unique.
        evaluator: Checks each draft. None means every draft is accepted.
        max_iterations: The most evaluator runs for one accepted draft.
            Must be at least 1.
    """

    model: model.Model
    instructions: str
    output_type: type[str] | type[pydantic.BaseModel] = str
    tools: Sequence[tool.Tool] = ()
    evaluator: Callable[[message.Message], evaluation.EvalResult] | None = None
    max_iterations: int = 3
    _logs: list[message.Message] = dataclasses.field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        """Checks the configuration so that run() cannot fail on it later.

        Raises:
            ValueError: `output_type` is a Pydantic class and `tools` is not
                empty, two tools share a name, or `max_iterations` is less
                than 1.
        """
        if issubclass(self.output_type, pydantic.BaseModel) and self.tools:
            raise ValueError("tools cannot be used with structured output")
        names = [item.name for item in self.tools]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"Duplicate tool names: {duplicates}")
        if self.max_iterations < 1:
            raise ValueError(
                f"max_iterations must be at least 1: {self.max_iterations=}"
            )

    def run(self, messages: Sequence[message.Message]) -> list[message.Message]:
        """Takes one turn in the conversation and returns what it added.

        Adds the system message from `instructions`, so `messages` must not
        contain one.

        Each draft from `model.generate()` goes through the evaluator, when
        there is one. A failed draft goes back to the model as an assistant
        message, followed by the feedback as a user message. This repeats
        until a draft passes or `max_iterations` evaluator runs are used up.
        In the second case the last draft is accepted. The count starts
        over for every accepted draft, and critiques of earlier drafts are
        not sent with later requests.

        When an accepted draft has tool calls, each one runs through the
        matching Tool. The draft and the tool results are added to the
        turn, and the model is asked again. The turn ends with the first
        accepted draft that has no tool calls.

        Args:
            messages: The conversation so far, as this agent should see it.
                Reasoning in it is never sent to the model.

        Returns:
            The messages this turn added, in order: every accepted draft
            that has tool calls, followed by its tool results, and then
            the final reply. Rejected drafts and critiques are not
            included. They only go to `logs`.

        Raises:
            exception.UnknownToolError: The model asked for a tool this
                agent does not have.
            exception.ToolExecutionError: A tool's function raised.
        """
        system = message.Message("system", self.instructions)
        tools_by_name = {item.name: item for item in self.tools}
        self._logs += [system, *messages]
        output: list[message.Message] = []
        while True:
            rejected: list[message.Message] = []
            for _ in range(self.max_iterations):
                draft = self.model.generate(
                    [system, *messages, *output, *rejected],
                    tools=self.tools,
                    output_type=self.output_type,
                )
                self._logs.append(draft)
                if self.evaluator is None:
                    break
                result = self.evaluator(draft)
                if result.passed:
                    break
                feedback = message.Message("user", result.feedback)
                self._logs.append(feedback)
                rejected += [draft, feedback]
            output.append(draft)
            if not draft.tool_calls:
                return output
            for call in draft.tool_calls:
                if call.name not in tools_by_name:
                    raise exception.UnknownToolError(call)
                output.append(tools_by_name[call.name](call))
                self._logs.append(output[-1])

    @property
    def logs(self) -> list[message.Message]:
        """Every message this agent has seen or produced, oldest first.

        Includes the system message, the input messages, every draft
        (accepted or rejected), every critique and every tool result. A
        new run starts with the system message again.
        """
        return list(self._logs)
