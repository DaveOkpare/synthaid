"""Bounded dialogue and a read-only Tool for a provider integration smoke."""

from collections.abc import Mapping

from agentinstruct import Agents, TaskContext, ToolContext
from agentinstruct.plans import FrozenJsonValue, JsonValue
from agentinstruct.traces import GenerationOutcome


class SmokeDialogue:
    async def setup(self, agents: Agents) -> None:
        if set(agents) != {"user", "assistant"}:
            raise ValueError("The smoke requires user and assistant participants")

    async def run(self, task: TaskContext, agents: Agents) -> GenerationOutcome:
        incoming = None
        for _ in range(task.max_rounds):
            for actor in ("user", "assistant"):
                async with agents[actor].interaction(task) as interaction:
                    incoming = (await interaction.turn(incoming)).last_reply
        return GenerationOutcome("terminated", "smoke_rounds_complete")


async def read_scenario(
    arguments: Mapping[str, FrozenJsonValue], context: ToolContext
) -> JsonValue:
    return {
        key: str(context.variables[key])
        for key in ("topic", "discussion_type", "language")
    }
