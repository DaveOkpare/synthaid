"""Call OpenAI and optionally revise its response from reviewer feedback."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from agentinstruct.judge import Evaluator, Judgment
from agentinstruct.tools import Tool


class ReviewExhausted(RuntimeError):
    """The reviewer rejected the final sample."""


@dataclass
class Agent:
    model: str
    instruction: str = ""
    tools: Sequence[Tool] = ()
    reviewer: Evaluator | None = None
    max_revisions: int = 1
    client: Any = field(default=None, repr=False, compare=False)
    history: list[Mapping[str, Any]] = field(default_factory=list, repr=False)

    async def generate(
        self, messages: Sequence[Mapping[str, Any]] = (), **options: Any
    ) -> Any:
        if type(self.max_revisions) is not int or self.max_revisions < 0:
            raise ValueError("max_revisions must be a nonnegative integer")
        history = self.history
        history.extend(messages)
        if not history or history[0].get("role") not in {"system", "developer"}:
            history.insert(0, {"role": "system", "content": self.instruction})
        for _ in range(self.max_revisions + 1):
            raw = await self._request(history, **options)
            draft = [item.model_dump(exclude_none=True) for item in raw.output]
            feedback = await self._review(history, draft)
            history.extend(draft if feedback is None else feedback)
            if feedback is None:
                return raw
        raise ReviewExhausted("Reviewer revisions exhausted")

    async def _request(self, history: list[Mapping[str, Any]], **options: Any) -> Any:
        client = options.pop("client", None)
        client = self.client if self.client is not None else client
        if client is None:
            raise ValueError("Agent requires an OpenAI client")
        return await client.responses.create(
            model=self.model,
            tools=[tool.schema() for tool in self.tools],
            stream=False,
            input=history,
            **options,
        )

    async def _review(
        self, history: list[Mapping[str, Any]], draft: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        if self.reviewer is None:
            return None
        result = await self.reviewer.evaluate([*history, *draft])
        if not isinstance(result, Judgment):
            raise ValueError("Reviewer must return a Judgment")
        if result.passed:
            return None
        if any(m.get("type") == "function_call" for m in draft):
            draft = [{"role": "assistant", "content": json.dumps(draft)}]
        return [*draft, {"role": "user", "content": result.feedback}]
