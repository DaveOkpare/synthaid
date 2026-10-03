# Doubleword with synthetic medagent scenario inputs

The opt-in live script projects two English scenario labels from an existing
medagent data file. It creates assistant/user Tasks with a read-only scenario Tool
and a model-backed final Judge. The application owns one AsyncOpenAI client around
the whole batch, with zero retries, a 20-request cap, 32,000 bytes per request,
45-second HTTP timeouts, and a 120-second generation deadline per Task.

Set DOUBLEWORD_API_KEY in the process environment and run:

```sh
uv run --locked python examples/doubleword-medagent/run.py \
  --seed-data /path/to/medagent/src/data/eval_pilot_40_sessions.json \
  --output /tmp/doubleword-medagent-smoke --allow-live
```

Without --allow-live, the script exits before writing files or making requests.
Each invocation needs a fresh output directory. It writes projected seeds.jsonl,
accepted native.jsonl/openai.jsonl exports, per-Episode evidence under runs/, and
report.json. The script succeeds only when both Episodes are accepted. Structural
judgment does not establish medical correctness or fitness for clinical use.

The projection retains topic, discussion type, language, synthetic source IDs,
and a source digest. It excludes biographies, contact information, narrative
briefs, EMR timelines, and session history. Original source files stay unchanged.
Task-file compilation is inert and does not require the custom Tool module:

```sh
uv run --locked agentinstruct validate examples/doubleword-medagent
```

For paid reverification, initialize clients through the CLI's declared credential
setting and keep the Tool factory importable:

```sh
PYTHONPATH=examples/doubleword-medagent uv run --locked agentinstruct reverify \
  /path/to/episode --package examples/doubleword-medagent --json
```

The separate review_smoke.py now demonstrates rejection, feedback-driven revision,
and private Tool visibility entirely offline through the direct API:

```sh
uv run --locked python examples/doubleword-medagent/review_smoke.py \
  --output /tmp/doubleword-review-offline
```

Historical live results remain in the [original smoke report](../../research/doubleword-live-smoke-2026-09-30.md)
and [review experiment report](../../research/doubleword-review-live-2026-10-01.md).
Those reports describe the earlier implementation and were not rerun for this
refactor. No live inference is required by the core verification suite.
