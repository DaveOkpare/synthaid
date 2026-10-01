"""Explicit scripted fault injection, distinct from the live model participants."""

import json

from agentinstruct import FunctionCall, Message, Observation, ToolCall
from agentinstruct.plans import AgentPlan


class ProbeAssistant:
    """Reject a Tool proposal, then a reply, or deliberately exhaust revisions."""

    def __init__(self, plan: AgentPlan) -> None:
        self.exhaust = plan.base_instruction.strip() == "exhaust"
        self.proposals = 0

    async def generate(self, observation: Observation) -> Message:
        self.proposals += 1
        if self.exhaust or self.proposals == 1:
            return Message(
                "assistant",
                "BLOCK_THIS_CALL",
                tool_calls=(
                    ToolCall(
                        f"blocked-{self.proposals}", FunctionCall("read_scenario", {})
                    ),
                ),
            )
        if self.proposals == 2:
            return Message(
                "assistant",
                tool_calls=(
                    ToolCall("allowed-call", FunctionCall("read_scenario", {})),
                ),
            )
        if self.proposals == 3:
            return Message("assistant", "REJECT_THIS_REPLY")
        # The saved Tool result must still be visible after the reply was rejected.
        result = next(m for m in observation.messages if m.role == "tool")
        return Message("assistant", "Accepted scenario: " + result.content)


class ProbeUser:
    def __init__(self, plan: AgentPlan) -> None:
        pass

    async def generate(self, observation: Observation) -> Message:
        return Message(
            "assistant",
            json.dumps(
                {
                    "seen": [m.content for m in observation.messages],
                    "private_tools_visible": any(
                        m.role == "tool" or m.tool_calls for m in observation.messages
                    ),
                    "review_feedback": observation.review_feedback,
                }
            ),
        )
