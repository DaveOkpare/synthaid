"""Generate return-policy data using the existing public library interface."""

import csv
from collections.abc import Iterator
from pathlib import Path

from agentinstruct import Runner, TaskPackage, export_openai, generate_sync


def prepare(source: Path) -> Iterator[dict[str, str | int | bool]]:
    """Domain preparation stays ordinary Python, outside inference execution."""
    with source.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            opened = row["opened"].strip().casefold()
            if opened not in {"yes", "no"}:
                raise ValueError("opened must be yes or no")
            yield {
                "id": row["id"].strip(),
                "days": int(row["days"]),
                "opened": opened == "yes",
            }


if __name__ == "__main__":
    task_dir = Path(__file__).parent
    package = TaskPackage.load(task_dir)
    result = generate_sync(
        package,
        runner=Runner(output_dir="runs/customer-support"),
        seeds=prepare(task_dir / "orders.csv"),
    )
    dataset = result.path / "training.jsonl"
    count = export_openai([trace.path for trace in result.traces], dataset)
    print(f"Exported {count} accepted traces to {dataset}")
    print(dict(result.counts))
