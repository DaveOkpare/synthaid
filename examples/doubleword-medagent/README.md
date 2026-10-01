# Doubleword with medagent scenario seeds

This opt-in live smoke uses the existing OpenAI-compatible Chat Completions
adapter at `https://api.doubleword.ai/v1`. It generates two short user–assistant
dialogues, calls a read-only scenario Tool, and asks a model Verifier for a
locally validated JSON-schema decision. Accepted Traces are exported in native
and OpenAI JSONL formats. Verification checks dialogue/Tool structure, not
medical correctness or fitness for clinical use.

The selected model is `Qwen/Qwen3.6-35B-A3B-FP8`, with temperature zero,
`reasoning_effort = "none"`, and at most 384 completion tokens per request.
The script caps each invocation at 20 HTTP requests (including Verification),
32,000 request-body bytes per call, 45-second HTTP timeouts, and 120 seconds
of generation per Seed. There are no retries. The custom Environment deliberately
ends after two user–assistant rounds; this is a bounded smoke, not a complete
clinical session or a model-directed completion benchmark.

The smaller `Qwen/Qwen3.5-9B` passed connectivity and a named Tool probe but
skipped automatic Tool calls in the initial live dialogues. Their rejected
Traces and empty default exports were retained. Doubleword's
[Rig guide](https://docs.doubleword.ai/inference-api/integrations/rig) documents
similar small-model Tool-selection behavior. Model-specific results and the
documentation research are in [the research note](../../research/doubleword-inference.md).
The [live report](../../research/doubleword-live-smoke-2026-09-30.md) records the
mixed result: Qwen3.6 produced one accepted nutrition Trace and one rejected
conflicting-advice Trace. The full two-accepted-record target remains unmet.

## Run

Set `DOUBLEWORD_API_KEY` in the process environment. The framework reads it only
at runtime; never put the key in `task.toml`, a Seed, or a command-line argument.
From the repository root:

```sh
uv run --locked python examples/doubleword-medagent/run.py \
  --seed-data /path/to/medagent/src/data/eval_pilot_40_sessions.json \
  --output /tmp/doubleword-medagent-smoke \
  --allow-live
```

Choose a new output directory for each invocation. Without `--allow-live`, the
script exits before creating an output directory or issuing requests. A run
exits unsuccessfully if it does not produce two accepted exports; rejected or
failed evidence remains available in `runs/` and `report.json`.

`medagent_seeds` projects two English scenario labels from the 40-session pilot:
conflicting advice and general nutrition. The supplied medagent sampler describes
the source cohort as generated personas. Only topic, discussion type, language,
synthetic source IDs and a source-file digest enter the new Seeds. Patient
biographies, names, contact information, narrative briefs, EMR timelines, and
session histories are excluded. The original medagent files remain unchanged.
Source references remain in Trace provenance; the model Verifier can see recorded
Trace data. This projection is intentionally smaller than a full medagent scenario.

For offline validation using the two bundled generic examples:

```sh
PYTHONPATH=examples/doubleword-medagent uv run --locked agentinstruct validate examples/doubleword-medagent
```

Use the `path` printed by `run.py` with `agentinstruct inspect`; `native.jsonl`,
`openai.jsonl`, the projected `seeds.jsonl`, and the per-call usage report are
written to the selected output directory. For reverification, keep
`smoke_components` importable and use the recorded Trace path:

```sh
PYTHONPATH=examples/doubleword-medagent uv run --locked agentinstruct reverify /path/to/trace --json
```

Reverification is another paid model call and is separate from the script's
per-invocation cap. `store: false` is a request field, not proof of account-level
zero-data-retention. Only synthetic, non-personal scenario content was used in
this smoke; consult Doubleword's [data policy](https://doubleword.ai/data-usage-policy/)
before using other data. Reasoning retention, Responses, async/batch execution,
parallel Tools, and clinical quality are outside the tested claim.

## Per-turn Review, Revision, and Tool effects

The separate experiment enables a model Reviewer on the assistant, with a strict
Tool-use rubric and two revisions per proposed Message. It keeps the original
participant prompts and final Verifier. It also runs two explicitly scripted
negative controls against the live model Reviewer: a bad Tool call followed by a
bad reply, and repeated bad Tool calls until revisions are exhausted.

```sh
uv run --locked python examples/doubleword-medagent/review_smoke.py \
  --seed-data /path/to/medagent/src/data/eval_pilot_40_sessions.json \
  --output /tmp/doubleword-review-smoke \
  --allow-live
```

This invocation shares a 48-request cap across all three experiments, with the
same per-request size/token limits as the original smoke. Generation has a
240-second deadline per Seed. `--natural-only` omits the scripted controls.
Task variants are saved in the output directory, leaving the original task intact.
The Tool audit writes a local `effects.jsonl` entry only when the Tool executes,
including whether its accepted call was already durable. It performs no external
mutation. `requests.jsonl` records JSON payloads and status codes without HTTP
headers; payloads include review feedback and the projected scenario data.

`report.json` records every review verdict, proposal, revision count, Tool effect,
conversation, and model usage. Default OpenAI exports still require final
Verification; the scripted controls deliberately have no final Verifier and
remain unverified. A zero script exit means the experiment was recorded, not that
all model judgments were correct. Inspect the reported outcomes and verdicts.

The [1 October live report](../../research/doubleword-review-live-2026-10-01.md)
records both the initial Reviewer errors and the successful follow-up after its
instruction was clarified. No inference retries, relaxed thresholds, or forced
Tool execution were used to make the natural scenarios pass.
