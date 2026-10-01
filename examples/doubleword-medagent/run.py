"""Opt-in, capped live smoke using non-personal projections of medagent seeds."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path

import httpx

from agentinstruct import (
    Inspector,
    Runner,
    TaskPackage,
    export_native,
    export_openai,
    load_trace,
)
from agentinstruct.plans import JsonValue, ProviderPlan, json_value
from agentinstruct.providers import ChatCompletionsProvider

TOPICS = (
    "Interpreting conflicting advice given by two different providers",
    "General nutrition and healthy-eating plan",
)


def medagent_seeds(path: Path) -> list[dict[str, JsonValue]]:
    """Project two scenario labels; never copy biographies, briefs or records."""
    raw = path.read_bytes()
    records = json.loads(raw)
    selected: list[dict[str, JsonValue]] = []
    for topic in TOPICS:
        matches = [
            (record, segment)
            for record in records
            if record["patient"]["language"] == "English"
            for segment in record["session"]["segments"]
            if segment["specific_condition_name"] == topic
        ]
        if not matches:
            raise ValueError(f"Source has no English scenario for {topic!r}")
        record, segment = matches[0]
        selected.append(
            {
                "id": f"medagent-smoke-{len(selected) + 1:02d}",
                "scenario": {
                    "topic": topic,
                    "discussion_type": segment["discussion_type"],
                    "language": "English",
                },
                "source": {
                    "file": path.name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "seed_id": record["seed_id"],
                    "segment_id": segment["segment_id"],
                },
            }
        )
    return selected


class CallBudget:
    def __init__(self, limit: int = 20) -> None:
        self.calls = 0
        self.limit = limit


class BoundedTransport(httpx.AsyncBaseTransport):
    """Cap all generation and judge HTTP calls without altering request bodies."""

    def __init__(self, budget: CallBudget) -> None:
        self.budget = budget
        self.transport = httpx.AsyncHTTPTransport(retries=0)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self.budget.calls >= self.budget.limit or len(request.content) > 32_000:
            raise httpx.RequestError("Smoke request budget exceeded", request=request)
        self.budget.calls += 1
        return await self.transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self.transport.aclose()


async def run(source: Path, output: Path) -> dict[str, JsonValue]:
    if not os.environ.get("DOUBLEWORD_API_KEY"):
        raise ValueError("Set DOUBLEWORD_API_KEY in the process environment")
    package = TaskPackage.load(Path(__file__).parent)
    seeds = medagent_seeds(source)
    report = package.validate(seeds=seeds)
    if not report.valid:
        raise ValueError("Projected seeds did not pass offline validation")
    (output / "seeds.jsonl").write_text(
        "".join(json.dumps(seed) + "\n" for seed in seeds)
    )
    budget = CallBudget()

    def provider(plan: ProviderPlan) -> ChatCompletionsProvider:
        return ChatCompletionsProvider(
            plan, transport=BoundedTransport(budget), timeout_seconds=45.0
        )

    result = await Runner(output_dir=output / "runs", provider_factory=provider).run(
        package, seeds=seeds
    )
    native_count = export_native([result.path], output / "native.jsonl")
    dataset_count = export_openai([result.path], output / "openai.jsonl")
    traces = [load_trace(item.path) for item in result.traces]
    model_calls = [
        event
        for trace in traces
        for event in (
            *trace.events,
            *(event for attempt in trace.verification for event in attempt.events),
        )
        if event.kind == "model_call"
    ]
    evidence: dict[str, JsonValue] = {
        "run": json_value(result.to_dict()),
        "inspection": Inspector(result.path).summary(),
        "requests": budget.calls,
        "native_count": native_count,
        "openai_count": dataset_count,
        "model_calls": [json_value(event.data) for event in model_calls],
        "scope": "Structural provider smoke; not clinical-quality validation",
    }
    (output / "report.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("Pass --allow-live to authorize this capped paid provider smoke")
    if args.output.exists():
        parser.error("Choose a new output directory to preserve earlier evidence")
    args.output.mkdir(parents=True)
    evidence = asyncio.run(run(args.seed_data, args.output))
    print(
        json.dumps(
            {
                key: evidence[key]
                for key in ("run", "requests", "native_count", "openai_count")
            }
        )
    )
    if evidence["native_count"] != 2 or evidence["openai_count"] != 2:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
