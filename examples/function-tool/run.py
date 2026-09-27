"""Run a reviewed local function Tool without a Provider or credentials."""

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

from agentinstruct import (
    FunctionCall,
    FunctionTool,
    Message,
    Observation,
    Runner,
    TaskPackage,
    ToolCall,
    ToolContext,
)
from agentinstruct.plans import FrozenJsonValue, JsonValue


class GreetingAgent:
    async def generate(self, observation: Observation) -> Message:
        if not observation.messages:
            return Message(
                "assistant",
                "Capitalize the greeting.",
                tool_calls=(
                    ToolCall(
                        "greeting-1",
                        FunctionCall(
                            "uppercase", {"text": observation.instruction.strip()}
                        ),
                    ),
                ),
            )
        result = json.loads(observation.messages[-1].content)
        return Message("assistant", str(result["text"]))


async def uppercase(
    args: Mapping[str, FrozenJsonValue], context: ToolContext
) -> JsonValue:
    return {"text": str(args["text"]).upper(), "actor": context.actor_id}


async def main(output: Path) -> None:
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: GreetingAgent(),
        tool_factory=lambda plan: FunctionTool(plan, uppercase),
    ).run(TaskPackage.load(Path(__file__).parent))
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs"))
    asyncio.run(main(parser.parse_args().output))
