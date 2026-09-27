"""Run ordered, reviewed Agent Tools with a recoverable failure, fully offline."""

import argparse
import asyncio
import json
from pathlib import Path

from agentinstruct import (
    AgentTool,
    FunctionCall,
    Message,
    Observation,
    Runner,
    TaskPackage,
    ToolCall,
    load_trace,
)


class LabelAgent:
    async def generate(self, observation: Observation) -> Message:
        if not observation.messages:
            labels = (observation.instruction.strip(), "missing", "Grace")
            return Message(
                "assistant",
                "Summarize these three labels in order.",
                tool_calls=tuple(
                    ToolCall(
                        f"label-{index}", FunctionCall("summarize", {"text": label})
                    )
                    for index, label in enumerate(labels, start=1)
                ),
            )
        summaries = []
        for message in observation.messages:
            if message.role == "tool":
                result = json.loads(message.content)
                summaries.append(result.get("summary", "Unavailable"))
        return Message("assistant", " | ".join(summaries))


class SummarizingAgent:
    async def generate(self, observation: Observation) -> Message:
        text = json.loads(observation.messages[0].content)["text"]
        if text == "missing":
            raise ValueError("The offline fixture deliberately simulates a failure")
        return Message("assistant", json.dumps({"summary": text.upper()}))


async def main(output: Path) -> None:
    result = await Runner(
        output_dir=output,
        agent_factory=lambda _: LabelAgent(),
        tool_factory=lambda plan: AgentTool(
            plan, SummarizingAgent, instruction="Summarize the label in uppercase."
        ),
    ).run(TaskPackage.load(Path(__file__).parent))
    print(json.dumps(result.to_dict(), indent=2))
    print(load_trace(result.traces[0].path).conversation[-1].message.content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs"))
    asyncio.run(main(parser.parse_args().output))
