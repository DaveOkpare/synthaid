# V1 Agent Trace Generation implementation map

- **01 — resolved:** [Bootstrap an executable typed package](issues/01-bootstrap-executable-typed-package.md#answer).
  The installed CLI, locked uv workflow, typing metadata, and CI checks are in
  place. See [development commands](../../README.md#development) for setup and
  verification.
- **02 — resolved:** [Validate and compile one seeded Task Package](issues/02-validate-compile-seeded-task.md#answer).
  A strict single-Agent JSON compiler and model-free `validate` command now
  produce immutable Run Plans with stable digests. See
  [validation usage](../../README.md#validate-a-task-package) and the
  [example package](../../examples/single-agent/task.toml). Compilation and
  rendering are now exercised through ticket 03's agreed Runner seam.
- **03 — resolved:** [Generate one deterministic single-agent Trace](issues/03-generate-deterministic-single-agent-trace.md#answer).
  The asynchronous Runner, synchronous wrapper, scripted `run` CLI, fresh
  trace-bound component factories, durable Message Commits and complete native
  snapshots are implemented. Persisted Trace inspection and status-selected
  native export need no live Runner. See [generation usage](../../README.md#generate-a-trace)
  and the [scripted example](../../examples/scripted-single/task.toml).

- **04 — resolved:** [Generate and export a two-agent dialogue](issues/04-generate-export-two-agent-dialogue.md#answer).
  Either generic participant may initiate or be the explicit target. Dialogue
  relays accepted references, retains full shared history, and distinguishes
  accepted completion from round/timeout truncation. Target-oriented OpenAI
  JSONL export and the thin export CLI read complete persisted snapshots and
  require explicit selection of non-accepted statuses. See
  [dialogue generation and export](../../README.md#generate-and-export-a-dialogue)
  and the [scripted dialogue package](../../examples/scripted-dialogue/task.toml).

- **05 — resolved:** [Verify and reverify sealed Traces](issues/05-verify-reverify-sealed-traces.md#answer).
  Weighted Boolean Verification now runs after durable generation sealing, records
  immutable versioned attempts, and preserves all generation bytes on reverification.
  Snapshot inspection and exports select the latest or an explicit valid decision,
  retain earlier valid eligibility after judge errors, and preserve generation
  failures. Shared scoring is ready for ticket 06. See
  [verification usage](../../README.md#verify-and-reverify-traces) and the
  [offline verified example](../../examples/verified-single/task.toml).

- **06 — resolved:** [Review and revise conversational Messages](issues/06-review-revise-conversational-messages.md#answer).
  Each Agent may use a fresh Reviewer with stable rendered instructions and a
  weighted Rubric. Per-Message review, private revision feedback, exact rejected
  proposal Events, explicit conversational exhaustion fallback, and linked review
  evidence now guard commits and completion. Initial and revised list Actions
  retain independent Message budgets. See
  [review usage](../../README.md#review-and-revise-messages) and the
  [offline reviewed dialogue](../../examples/reviewed-dialogue/task.toml).

- **07 — resolved:** [Review Tool calls before executing effects](issues/07-review-tool-calls-before-effects.md#answer).
  Task-wide Tool declarations and Agent assignments compile into immutable Plans.
  Per-Message review now gates durable private intent before argument validation
  and effects, followed by validated private results and independently reviewed
  shared replies. Actor-aware custom Tools and the function adapter retain
  callable provenance; Observation/export projections enforce ownership. See
  [Tool usage](../../README.md#review-tool-calls-before-effects) and the
  [offline function example](../../examples/function-tool/run.py).

- **08 — resolved:** [Support robust multi-Tool interactions](issues/08-support-robust-multi-tool-interactions.md#answer).
  Whole-Message review now gates ordered multi-call execution, with separate
  durable results, actor-scoped stable call IDs, optional typed execution-error
  results, and retained partial progress. `AgentTool` uses fresh isolated
  subordinates, rejects nested effects, and records factory provenance.
  Target-only private export preserves matching IDs. See
  [Tool usage](../../README.md#review-tool-calls-before-effects) and the
  [offline multi-Tool example](../../examples/multi-tool/run.py).

- **09 — resolved:** [Retain history across Task Steps](issues/09-retain-history-across-task-steps.md#answer).
  Ordered immutable Step Plans compile every participant's temporary additions
  before generation. Base instructions, configured review thresholds, shared
  Conversation, and actor-private Tool history persist as only active additions
  change. Target and Environment controls cross the existing reviewed durable
  Tool-call boundary, with ordered progress, isolated calls, safe completion,
  and coherent step references. See
  [Task Step usage](../../README.md#retain-history-across-task-steps) and the
  [offline stepped dialogue](../../examples/stepped-dialogue/run.py).

- **10 — resolved:** [Run deterministic JSON and JSONL Seed collections](issues/10-run-json-jsonl-seed-collections.md#answer).
  One Run now processes ordered records with independent immutable Plans, stable
  Seed IDs, unique Trace attempts, all five status counts, per-Trace durable index
  publication, and fresh runtime state. Invalid records retain standalone input
  evidence; source failures preserve available attempts. Fail-fast stops only
  invalid/failed attempts, and model-free collection validation shares the compiler.
  See [collection usage](../../README.md#run-a-seed-collection) and the
  [offline example](../../examples/seed-collection/task.toml).

- **11 — resolved:** [Complete Seed sources and package safety](issues/11-complete-seed-sources-package-safety.md#answer).
  CSV exact-header bindings, deterministic directory preflight, Python iterable
  Seeds, and offline Seed schemas share compilation and durable failure scoping.
  Portable names, confined references, precise layouts, and safe export/output
  destinations protect authoring and immutable evidence. See
  [source usage](../../README.md#run-a-seed-collection), the
  [mixed-source package](../../examples/seed-sources/task.toml), and the
  [iterable example](../../examples/seed-sources/run.py).

- **12 — resolved:** [Generate through a Chat Completions Provider](issues/12-generate-through-chat-completions-provider.md#answer).
  Immutable semantic Provider models, per-surface capabilities, lazy stateless
  Chat Completions inference, strict response normalization and classified safe
  failures now drive model Agents through the existing reviewed acceptance boundary.
  Runner preflight and cleanup, private actor-relative history and model-call
  evidence are exercised using deterministic HTTP transports. See
  [Provider usage](../../README.md#generate-through-a-chat-completions-provider)
  and the [model example](../../examples/chat-completions/task.toml).

- **13 — resolved:** [Use Pydantic structured outputs for quality gates](issues/13-pydantic-structured-quality-gates.md#answer).
  Immutable schema snapshots and typed Provider results now support Pydantic
  classes and explicit JSON Schema with mandatory local validation. Model Reviewers
  score exact active criteria before effects; model Verifiers use rendered Task
  instructions and append-only attempt evidence, including endpoint provenance.
  Reverification binds policy overrides to persisted Seeds without changing
  generation files. See [structured quality usage](../../README.md#use-structured-quality-gates)
  and the [offline example](../../examples/structured-quality/run.py).

- **14 — resolved:** [Responses parity and private reasoning](issues/14-responses-parity-private-reasoning.md#answer).
  OpenAI now defaults to stateless Responses with complete accepted history,
  shared structured validation and normalized function-call/refusal/usage behavior.
  Typed reasoning controls and retention policy preserve private native evidence;
  accepted Tool continuation never replays rejected drafts or another actor's
  reasoning. See [Responses usage](../../README.md#generate-through-responses-and-retain-private-reasoning).

- **15 — resolved:** [Add tested vLLM Provider profiles](issues/15-tested-vllm-provider-profiles.md#answer).
  External vLLM inference now has immutable per-model/per-surface declarations,
  typed native/reasoning options, combined-feature preflight and private Tool
  continuation. Compatible Responses also requires its own portable declaration.
  Deterministic contracts and an explicitly opt-in report-producing live harness
  cover the declared request profile. The pinned Qwen3 candidate is unverified;
  no real-server compatibility claim is made. See
  [Provider usage](../../README.md#use-explicit-vllm-and-compatible-endpoint-profiles)
  and [conformance instructions](../../conformance/vllm/README.md).

- **16 — resolved:** [Load custom components through explicit references](issues/16-load-custom-components.md#answer).
  A small built-in registry and explicit Python class references now validate
  lazily without instance/client construction, then create fresh protocol-checked
  runtime components. Custom multi-party Environments use narrow Context/facades;
  function and Agent Tool adapters retain reviewed effects and actual factory
  identity/configuration. Source digests and package-local implementation snapshots
  preserve provenance. See [component authoring](../../README.md#load-custom-components)
  and the [offline fixture](../../examples/custom-components/task.toml).

- **17 — resolved:** [Inspect recorded Runs and Traces](issues/17-inspect-recorded-runs-traces.md#answer).
  Persisted Run discovery follows ordered confined relative references and exposes
  current Trace decisions separately from historical Run counts. The Inspector,
  JSON/static CLI and paginated terminal UI cover accepted and participant views,
  private Tools, review/Verification evidence, Steps, reasoning retention,
  provenance, failures and artifacts without invoking components or changing
  recorded evidence. See [inspection usage](../../README.md#inspect-recorded-runs-and-traces).

- **18 — resolved:** [Harden failure persistence and provenance](issues/18-harden-failure-persistence-provenance.md#answer).
  Narrow safe failure/cause evidence, strict JSON boundaries and runtime credential
  redaction preserve accepted partial history and reviewed effects. Cancellation
  persists failed generation or unverified sidecars before propagating where
  storage permits; configured cleanup deadlines and independent resource closing
  survive recording failures. Source/journal/directory sync precedes index
  publication, and safe Seed references match snapshots. See
  [failure behavior](../../README.md#failure-evidence-and-cleanup).

Ticket 19 remains unimplemented.
