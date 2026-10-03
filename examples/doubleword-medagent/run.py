"""Opt-in, capped live SDK smoke using non-personal scenario projections."""

import argparse
import asyncio
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from openai import AsyncOpenAI

from agentinstruct import Runner
from agentinstruct.adapters.task_files import load_tasks

TOPICS = (
    "Interpreting conflicting advice given by two different providers",
    "General nutrition and healthy-eating plan",
)


def projected_seed(
    record: Mapping[str, Any],
    segment: Mapping[str, Any],
    source: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    scenario: dict[str, Any] = {
        "topic": segment["specific_condition_name"],
        "discussion_type": segment["discussion_type"],
        "language": "English",
    }
    return {
        "id": f"medagent-smoke-{index:02d}",
        "scenario": scenario,
        "source": {
            **source,
            "seed_id": record["seed_id"],
            "segment_id": segment["segment_id"],
        },
    }


def medagent_seeds(path: Path) -> list[dict[str, Any]]:
    """Project two scenario labels; never copy biographies, briefs or records."""
    raw = path.read_bytes()
    records = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    source: dict[str, Any] = {"file": path.name, "sha256": digest}
    selected: list[dict[str, Any]] = []
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
        selected.append(projected_seed(record, segment, source, len(selected) + 1))
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


async def run(source: Path, output: Path) -> dict[str, Any]:
    key = os.environ["DOUBLEWORD_API_KEY"]
    seeds, budget = medagent_seeds(source), CallBudget()
    async with AsyncOpenAI(
        base_url="https://api.doubleword.ai/v1",
        api_key=key,
        max_retries=0,
        http_client=httpx.AsyncClient(transport=BoundedTransport(budget), timeout=45),
    ) as client:
        tasks = load_tasks(
            Path(__file__).parent, seeds=seeds, clients={"doubleword": client}
        )
        episodes = await Runner(tasks, output_dir=output / "runs", client=client).run()
    accepted = [episode for episode in episodes if episode.status == "accepted"]
    artifacts(output, seeds, accepted)
    report = {
        "requests": budget.calls,
        "exports": len(accepted),
        "episodes": [
            {"id": e.id, "status": e.status, "path": str(e.path)} for e in episodes
        ],
    }
    (output / "report.json").write_text(json.dumps(report, indent=2))
    return report


def artifacts(output: Path, seeds: list[dict[str, Any]], episodes: list[Any]) -> None:
    from agentinstruct.episode import canonical_json

    values = {
        "seeds.jsonl": seeds,
        "native.jsonl": [e.to_dict() for e in episodes],
        "openai.jsonl": [{"messages": e.training_messages()} for e in episodes],
    }
    for name, rows in values.items():
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.writelines(canonical_json(row) + "\n" for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    if not args.allow_live:
        parser.error("Pass --allow-live to authorize at most 20 model calls")
    if not os.environ.get("DOUBLEWORD_API_KEY"):
        parser.error("Set DOUBLEWORD_API_KEY in the process environment")
    args.output.mkdir(parents=True, exist_ok=False)
    report = asyncio.run(run(args.seed_data, args.output))
    print(json.dumps(report))
    raise SystemExit(0 if report["exports"] == 2 else 1)


if __name__ == "__main__":
    main()
