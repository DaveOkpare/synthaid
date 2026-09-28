"""Run a reviewed two-step dialogue with retained private Tool history, offline."""

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
    load_trace,
)
from agentinstruct.plans import AgentPlan, FrozenJsonValue, JsonValue


class DemoAgent:
    def __init__(self, plan: AgentPlan) -> None:
        self.target = plan.target
        self.requests = 0

    async def generate(self, observation: Observation) -> Message:
        self.requests += 1
        if not self.target:
            return Message(
                "assistant",
                (
                    "Please look up my greeting.",
                    "Ready for the conclusion?",
                    "Please finish with the greeting.",
                )[self.requests - 1],
            )
        if self.requests in {1, 3, 5}:
            name, arguments, explanation = {
                1: ("lookup", {}, "Look up the greeting."),
                3: ("advance_step", {"step_id": "conclude"}, "Move to the conclusion."),
                5: ("complete_task", {}, "The greeting is ready; complete the Task."),
            }[self.requests]
            return Message(
                "assistant",
                explanation,
                tool_calls=(
                    ToolCall(f"call-{self.requests}", FunctionCall(name, arguments)),
                ),
            )
        greeting = next(
            json.loads(message.content)["greeting"]
            for message in observation.messages
            if message.tool_call_id == "call-1"
        )
        return Message("assistant", f"{observation.step_id}: {greeting}")


async def lookup(
    arguments: Mapping[str, FrozenJsonValue], context: ToolContext
) -> JsonValue:
    return {"greeting": f"Hello, {context.variables['name']}."}


async def main(output: Path) -> None:
    result = await Runner(
        output_dir=output,
        agent_factory=DemoAgent,
        tool_factory=lambda plan: FunctionTool(plan, lookup),
    ).run(TaskPackage.load(Path(__file__).parent))
    trace = load_trace(result.traces[0].path)
    print(json.dumps(result.to_dict(), indent=2))
    print(f"Generation: {trace.generation.state}; {len(trace.conversation)} commits")
    for commit in trace.conversation:
        message = commit.message
        print(
            f"{commit.step_id} / {message.actor_id} / {message.role}: {message.content}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs"))
    asyncio.run(main(parser.parse_args().output))
