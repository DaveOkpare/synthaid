# Customer-support data generation

This example uses the current public API; it does not require the proposed refactor. No live model call was made while preparing it.

Two Agents simulate return requests under a fictional retailer policy: items must be unopened and received at most 14 days ago. The CSV contains one eligible and one ineligible customer scenario. Both can become useful training Traces if the support conversation passes Verification: an ineligible return is not itself a rejected Trace.

```text
CSV -> prepare() -> Seeds -> Task compilation
                             |
                      customer <-> support
                      own Review   own Review
                             |
                      final Verification
                             |
                      accepted JSONL export
```

## Use

From the repository root, validate the default CSV source offline:

```sh
uv run agentinstruct validate .scratch/lean-core-refactor/examples/customer-support --json
```

Before generation, replace `name = "your-model"` in [task.toml](task.toml) with a model available to your account that supports Responses, function Tools, and JSON Schema output. Set `OPENAI_API_KEY` in your runtime environment, then run:

```sh
uv run python .scratch/lean-core-refactor/examples/customer-support/run.py
```

[run.py](run.py) prepares the CSV as typed Python records, invokes the Task, and exports accepted Traces to the generated Run's `training.jsonl`. Task seed defaults still allow the built-in CSV reader for CLI validation/run. Each input record creates one Trace attempt; Review or Verification may reject it or fail, so two inputs do not guarantee two exported records.

Agent-specific Reviewer declarations live under `[agents.user.reviewer]` and `[agents.assistant.reviewer]`. The separate `[verifier]` judges whole Traces. The single `resolve` Task Step exposes the framework completion control to the target support Agent.

The caller only needs Task loading, generation, and export. Instructions, rubrics, and model defaults remain in the Task directory. No custom component classes or new authoring API are needed for this domain.

## Refactor connection

The proposed per-Agent runtime will own the Review loop behind the same interface. Today that loop is in Interaction. This example's public calls and task files remain valid before and after the planned refactor. See the [interface sketch](../../interfaces.md).
