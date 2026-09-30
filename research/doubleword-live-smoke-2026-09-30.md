# Doubleword live smoke: 30 September 2026

The existing `openai-compatible` Chat adapter works with Doubleword's realtime
endpoint without changes to the library. Live evidence covers text generation,
function-call normalization, a private Tool/result/continuation exchange,
Pydantic-backed JSON-schema Verification, saved inspection, export filtering,
and append-only reverification. **The full two-case acceptance target did not
pass:** automatic Tool selection remained unreliable for the conflicting-advice
scenario. No criteria were relaxed and no rejected Trace was promoted.

## Observed results

| Check | Model | Result |
|---|---|---|
| Authenticated model listing | Account | HTTP 200, 36 visible models |
| Text connection, 64-token cap | Qwen3.5-9B | Exact requested reply, `connection-ok` |
| Two-Seed workflow | Qwen3.5-9B | 0 accepted, 2 rejected; both skipped the Tool |
| Named `read_scenario` call, 128-token cap | Qwen3.5-9B | Valid function name, ID, `{}` arguments; `tool_calls` finish |
| Automatic Tool probe | Qwen3.6-35B-A3B-FP8 | Valid `read_scenario` call |
| Same two-Seed workflow, unchanged prompts/rubric | Qwen3.6-35B-A3B-FP8 | 1 accepted (nutrition), 1 rejected (conflicting advice skipped Tool) |
| Accepted Trace reverification | Qwen3.6-35B-A3B-FP8 | Accepted again; generation files unchanged |

The smaller model also refused one simulator prompt and its Verifier interpreted
that refusal as failing the dialogue criterion. In both Runs, Verifier replies
were valid structured outputs and local schema/criterion validation succeeded.
The newer model's accepted Trace contains two user replies, two target replies,
one private Tool call and its matching result. Its default native and OpenAI
exports each contain exactly one record; explicit accepted/rejected native
selection contains both records. Static inspection and terminal navigation work
on the persisted Run. Both workflow invocations exit 1 because each fell short
of the harness's two-accepted-record target, even though provider requests and
individual downstream operations succeeded.

Doubleword independently documents small-model Tool-selection failures and
stronger results with Qwen3.6-35B-A3B in its
[Rig guide](https://docs.doubleword.ai/inference-api/integrations/rig).
Our small sample supports choosing the newer model for further Tool testing;
it does not establish universal reliability or clinical quality.

## Scope and inputs

Configuration is in [the runnable example](../examples/doubleword-medagent/README.md):
`https://api.doubleword.ai/v1`, `chat_completions`, Bearer credentials from
`DOUBLEWORD_API_KEY`, temperature 0, `reasoning_effort = "none"`, non-streamed,
no infrastructure retries. Workflow requests cap completion tokens at 384;
the separate connectivity and named-Tool probes use the smaller caps above.
Each workflow caps requests at 20 and request-body size at 32,000 bytes.

The supplied medagent source contains a generated cohort (see its
`src/sampling/patient.py` and `build_eval_patients.py`). From
`src/data/eval_pilot_40_sessions.json`, only these two non-personal scenario
projections were used:

- `EV000032/S-001`, `SEG-03`: interpreting conflicting advice from two providers.
- `EV000107/S-003`, `SEG-01`: general nutrition and a healthy-eating plan.

Source SHA-256:
`64539c819d297f630a2c28ea76897258abcefc26222fc0d745829a0017070ec1`.
The source remained unchanged. New Seeds contain topic, discussion type, English
language, synthetic source references and this digest. They omit names, phone
numbers, addresses, patient biographies, narrative briefs and EMR/session
histories. The model Verifier sees the projected Seed and recorded Conversation.
This is a reduced scenario test, not a replay of the full pilot session plans.

The API key was not printed, passed on the command line, or stored in artifacts.
A local scan of all 52 generated evidence files found no resolved API key.
Default data retention and private reasoning are not certified by this test;
the [documentation research](doubleword-inference.md) describes those boundaries.

## Usage and cost estimate

All counts include generation and Verification. The 3.6 group also includes the
separate automatic Tool probe and accepted Trace reverification; the 9B group
includes connectivity and the named Tool probe.

| Model | Inference requests | Input tokens | Output tokens | Estimated uncached USD |
|---|---:|---:|---:|---:|
| `Qwen/Qwen3.5-9B` | 12 | 5,914 | 640 | $0.00068740 |
| `Qwen/Qwen3.6-35B-A3B-FP8` | 13 | 9,717 | 963 | $0.00232338 |
| Total | 25 | 15,631 | 1,603 | **$0.00301078** |

Estimated from observed token counts and the published realtime input/output
rates: [9B](https://docs.doubleword.ai/inference-api/models/qwen-qwen3-5-9b)
($0.10/$0.15 per million),
[3.6](https://docs.doubleword.ai/inference-api/models/qwen-qwen3-6-35b-a3b-fp8)
($0.14/$1.00 per million). This is not an account invoice; cache accounting and
billing adjustments were not queried. All responses reported zero reasoning
tokens for these requests; generic Chat private-reasoning retention was not tested.

## Evidence and reproduction

Local, git-ignored evidence is retained under
`runs/doubleword-2026-09-30/`. Start with `summary.json`; it contains current
absolute paths to both Runs and the accepted export. The copied original reports
retain their original `/tmp` execution paths; the relative Run indexes were
successfully loaded from the persistent location without changing generation.

- 9B Run: `7542d026d01541dfbcc5d2b4b992a9cf`.
- 3.6 Run: `ba61dce1cfba49878df7488383e4e043`.
- Accepted Trace: `09c79193ba1442d0bc3164673784f92e`.
- `live-qwen36/openai.jsonl`: one accepted training-shaped record.
- `live-qwen36/native-all-statuses.jsonl`: both 3.6 Trace snapshots.
- `live-qwen36/downstream-checks.json`: reverification and immutability results.
- `live-qwen36/terminal-inspection.txt`: terminal navigation output.

Use the example's explicit `--allow-live` command for another bounded paid run.
Its offline validation, opt-in guard, lint, formatting, and strict typing passed;
60 focused provider, model-quality, and import-safety regression tests also passed.
Live outputs are intentionally excluded from Git. Responses, async/batch tiers,
parallel Tools, broad provider conformance, and clinical-quality scoring remain
outside this smoke.
