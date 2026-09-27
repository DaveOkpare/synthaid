# V1 Agent Trace Generation Framework

Status: ready-for-agent

Updated: 2026-09-27

## Problem Statement

Teams that create training and distillation data from agent interactions lack a small, reusable framework that treats generated traces as the primary product. Existing evaluation frameworks provide useful task packaging and verification patterns, while existing synthetic-data tools tend to focus on independent records rather than stateful interactions. Neither category cleanly supports seed-driven single-agent and multi-party generation, instructions revealed across task steps, participant-private tools, pre-acceptance review and revision, one retained accepted conversation, and post-generation verification.

The first consumer needs to generate patient–clinician conversations in which the clinician is the training target and the patient is a simulator. The framework itself must remain domain-neutral: its built-in dialogue uses `user` and `assistant`, and domain identities come from task instructions and seed data. Users need reproducible task packages, inspectable failures, deterministic seed processing, and export-ready target-agent data without having to build orchestration, review, provenance, and persistence themselves.

## Solution

Build an open-source Python library with a thin CLI for producing verified agent traces. A Harbor-inspired Task Package declares seed inputs, global variable bindings, agent specifications, base and task-step instructions, review rubrics, tools, an environment, local runtime settings, and a final verifier. A compiler binds that unresolved package to each Seed and produces one immutable Run Plan before any model execution.

A Prime Intellect-inspired Environment defines interaction control flow in ordinary Python through a small `setup`/`run`/`finalize` protocol. Built-in single-agent and two-party dialogue environments cover the initial workflows. Each runtime Agent exposes an Interaction whose `turn()` operation projects accepted history, invokes the model, independently reviews model-produced tool-call and conversational messages, executes only accepted tool calls, persists accepted messages, and returns only an accepted reply to the environment.

One Run processes every Seed in the selected source sequentially. Each Seed produces one independently recorded Trace. A Trace retains one canonical accepted Conversation across every Task Step, participant-private accepted tool exchanges, a separate Event stream for rejected or operational activity, immutable provenance, artifacts, and versioned Verification results. A post-generation Verifier returns weighted Boolean criterion verdicts, from which the framework derives a normalized score and terminal status. Native export retains complete selected traces; OpenAI-style dataset export selects accepted traces by default and projects the Conversation from the sole Target Agent's perspective.

## User Stories

1. As a task author, I want to define a generation Task as a versioned filesystem package, so that it can be reviewed, shared, and reproduced without custom orchestration code.
2. As a task author, I want the Task Package to have one declarative configuration file, so that seed, agent, environment, tool, review, and verification settings are discoverable in one place.
3. As a task author, I want to write agent instructions in Markdown, so that substantial prompts remain readable and versionable outside configuration syntax.
4. As a task author, I want to define a base instruction for every Agent, so that its persistent identity and behavior apply throughout a Trace.
5. As a task author, I want to omit Task Steps for a single-step Task, so that simple generation jobs remain simple.
6. As a task author, I want to declare ordered Task Steps for a multi-step Task, so that fresh phase-specific instructions can be revealed during one continuing interaction.
7. As a task author, I want every Task Step to contain role-specific instruction additions for each participating Agent, so that the same phase can guide participants differently.
8. As a task author, I want the previous step's instruction additions to expire when the next step begins, so that only the current phase's temporary guidance remains active.
9. As a task author, I want accepted Conversation history to survive every Task Step, so that later phases continue the same interaction rather than starting over.
10. As a task author, I want strict Jinja templating in base and step instructions, so that each Seed can produce a distinct scenario without duplicating Task Packages.
11. As a task author, I want missing or unknown template variables to fail before model execution, so that prompt mistakes do not consume provider resources.
12. As a task author, I want task-wide Variable aliases mapped to Seed fields with dot paths, so that templates use stable meaningful names instead of storage-specific expressions.
13. As a task author, I want Variable aliases to be globally unique, so that a rendered value has the same meaning for every Agent and Task Step.
14. As a task author, I want JSON dot paths to traverse nested mappings, so that structured Seed data can be used without flattening it first.
15. As a task author, I want CSV variables to address exact flat headers, so that CSV behavior is predictable without pretending rows contain nested objects.
16. As a task author, I want optional JSON Schema validation for Seeds, so that domain-specific input requirements can be enforced before generation.
17. As a task author, I want to point a Task at a JSON, JSONL, or CSV file, so that common existing Seed sources work directly.
18. As a task author, I want to point a Task at a directory plus a file glob, so that one Run can consume a collection of Seed files.
19. As a library caller, I want to provide Seeds as a Python iterable, so that records from databases or upstream pipelines do not need an intermediate file.
20. As a dataset producer, I want the framework to remain agnostic about how Seeds are created, so that Seed generation can evolve independently.
21. As a dataset producer, I want one Trace per Seed, so that each generated example has an unambiguous source record and execution history.
22. As a dataset producer, I want a stable Seed ID and a new Trace ID for every execution attempt, so that reruns can be compared without conflating input identity with execution identity.
23. As a task author, I want to select a declared Variable as the Seed ID, so that domain identifiers can remain stable across Runs.
24. As a task author, I want the framework to derive a canonical content-hash Seed ID when none is configured, so that every Seed is still addressable.
25. As a Run operator, I want Seed files and directory records processed deterministically, so that repeated Runs have explainable ordering.
26. As a Run operator, I want invalid individual Seeds recorded and skipped without stopping later Seeds by default, so that one bad record does not waste the rest of a collection.
27. As a Run operator, I want a fail-fast option, so that strict pipelines can stop after the first invalid or failed Trace.
28. As a task author, I want exactly one Agent marked as the Target Agent, so that dataset projection has one unambiguous training perspective.
29. As a task author, I want `target` to remain an explicit Boolean rather than being inferred from an Agent ID, so that either participant can be the training target.
30. As a task author, I want provider and model defaults declared at Task level with optional per-Agent overrides, so that common settings are concise while specialized participants remain possible.
31. As a task author, I want Reviewer model settings to inherit from their owning Agent or use explicit overrides, so that review quality and cost can be tuned independently when necessary.
32. As an agent integrator, I want an OpenAI-style Message model for model input and output, so that content, tool calls, tool results, names, and actor identity use a familiar structure.
33. As an agent integrator, I want an Agent to return one Message or an ordered list of Messages, so that ordinary responses and structured tool exchanges can share one contract.
34. As a task author, I want built-in OpenAI and OpenAI-compatible Provider integrations, so that a Task can run against hosted OpenAI or a compatible inference server without a custom adapter.
35. As an extension author, I want to implement a small custom Provider protocol, so that other inference services can participate without changing Agents, Reviewers, Verifiers, or the Runner.
36. As a Run operator, I want every Trace to receive fresh Agent and Interaction state, so that mutable state cannot leak between Seeds.
37. As a task author, I want a built-in single-agent Environment, so that non-dialogue generation uses the same review, persistence, and verification lifecycle.
38. As a task author, I want a built-in two-party dialogue Environment using generic `user` and `assistant` seats, so that domain-specific simulations do not require domain-specific framework types.
39. As a task author, I want to configure which dialogue participant initiates the interaction, so that either participant can send the first accepted message.
40. As a task author, I want the built-in dialogue to alternate participants after initiation, so that the ordinary back-and-forth workflow requires no turn graph.
41. As an environment author, I want to express custom interaction control flow in ordinary asynchronous Python, so that specialized multi-party protocols do not require a universal routing DSL.
42. As an environment author, I want a narrow immutable Task Context rather than the whole Run Plan, so that custom environments cannot depend on provider credentials, persistence internals, or final-verifier configuration.
43. As an environment author, I want lifecycle hooks for setup, run, and optional finalization, so that environment resources and artifacts can be managed without taking ownership of the Runner lifecycle.
44. As a Run operator, I want framework-owned timeouts, cleanup, and error capture around Environment hooks, so that custom environment failures still produce diagnosable records.
45. As a task author, I want maximum interaction limits and explicit termination versus truncation, so that successful completion is distinguishable from timeouts, caps, and failures.
46. As a task author, I want Task Step progression and completion to be built into stepped interactions, so that models can reach checkpoints without a separate workflow engine.
47. As a Tool author, I want a small asynchronous Tool protocol with an identifier, description, JSON input schema, optional output schema, and actor-aware call context, so that Tools are provider-independent and traceable.
48. As a task author, I want Tools declared once and assigned to specific Agents, so that capabilities are explicit and private by default.
49. As a Tool author, I want function and Agent-wrapped Tool adapters, so that existing Python capabilities and subordinate Agents can be exposed uniformly.
50. As a task author, I want tool-call Messages reviewed before execution, so that a rejected model proposal cannot cause an external effect.
51. As a task author, I want a Message containing multiple tool calls reviewed as one model proposal, so that the Reviewer evaluates the exact structured Message the model produced.
52. As a Run operator, I want accepted tool-call Messages persisted before execution, so that authorized intent remains durable even if execution later crashes.
53. As an Agent, I want validated tool-result Messages added to my private accepted history, so that I can use the result to produce the next proposal.
54. As a Simulator, I want another Agent's tool calls and results excluded from my Observation, so that private reasoning capabilities do not leak across participants.
55. As a Run inspector, I want accepted tool exchanges stored in canonical occurrence order, so that I can reconstruct exactly what happened.
56. As a Tool author, I want tool results validated against the declared protocol or schema, so that malformed execution output cannot silently become model context.
57. As a task author, I want Tool results validated rather than LLM-reviewed, so that framework-produced data is checked by its contract without unnecessary judge calls.
58. As a Run operator, I want tool execution errors recorded without retroactively rejecting the accepted call, so that intent and execution outcome remain distinct facts.
59. As a task author, I want Reviewers to be optional per Agent, so that straightforward or low-risk generators need not pay review cost.
60. As a task author, I want each Reviewer to use stable instructions and an Agent-specific base Rubric, so that pre-acceptance quality rules are explicit.
61. As a task author, I want current-step Rubric criteria appended to the base Rubric, so that phase-specific requirements augment rather than replace persistent requirements.
62. As a task author, I want every Criterion to have a unique identifier and positive weight, so that verdicts compose and scores are deterministic.
63. As a task author, I want a configurable normalized Reviewer threshold, so that acceptance can require all criteria or a weighted subset.
64. As a task author, I want Reviewer and Verifier thresholds configured separately, so that message safety and completed-Trace quality remain distinct decisions.
65. As a Reviewer author, I want to return one Boolean per active Criterion plus feedback, so that the framework owns scoring while the Reviewer owns judgment.
66. As a Run operator, I want incomplete, duplicate, unknown, or non-Boolean Reviewer verdicts treated as errors, so that malformed output cannot authorize a Message or effect.
67. As a task author, I want a configurable revision count per reviewed model Message, so that Agents can reflect on feedback without unbounded loops.
68. As an Agent, I want Reviewer feedback supplied when I revise a rejected proposal, so that the next proposal can address the failed criteria.
69. As a Simulator, I want rejected proposals and Reviewer feedback excluded from accepted Conversation history, so that later interaction is not contaminated by drafts that never occurred.
70. As a task author, I want optional acceptance of an outbound conversational draft after revision exhaustion to require explicit opt-in, so that the fallback is visible and intentional.
71. As a task author, I want tool-call Messages never force-accepted after revision exhaustion, so that liveness policy cannot authorize a rejected effect.
72. As a participant, I want only an accepted conversational Message handed to the other participant, so that every reply I observe has passed its quality boundary.
73. As a Run operator, I want each accepted Message committed independently with turn, step, actor, visibility, and causal references, so that partial progress is durable and auditable.
74. As a Run inspector, I want a failed Trace to retain an accepted tool call or result even if no outbound reply was accepted later, so that partial execution evidence is not discarded.
75. As a Run inspector, I want operational Events stored separately from the Conversation, so that drafts, reviews, model calls, errors, and lifecycle transitions remain inspectable without becoming model-visible history.
76. As a Run inspector, I want stable identifiers for Messages, Events, calls, reviews, turns, verification attempts, and artifacts, so that records can be joined without a graph database.
77. As a task author, I want one post-generation Verifier to evaluate the sealed Trace, so that dataset eligibility is independent from in-loop Reviewer decisions.
78. As a Verifier author, I want deterministic code and LLM judges to implement the same protocol, so that the framework can switch verification strategies without changing Trace semantics.
79. As a Verifier author, I want to return exactly one Boolean per declared weighted Criterion, so that the framework can derive a transparent normalized score.
80. As a Run operator, I want malformed or failed Verification recorded as `unverified` rather than as failed criteria, so that judge failure is not mistaken for poor generated data.
81. As a dataset curator, I want a successfully verified Trace marked `accepted` or `rejected` by a configured threshold, so that inclusion decisions are reproducible.
82. As a dataset curator, I want to reverify a sealed Trace without regenerating its Conversation, so that improved judges can be applied without repaying generation cost.
83. As a Run operator, I want every Seed attempt represented in the Run index, including invalid, failed, unverified, rejected, and accepted outcomes, so that collection counts are complete.
84. As a Run operator, I want every terminal Trace stored as a complete immutable export source before the next Seed begins, so that crashes cannot leave only an index entry.
85. As a Run operator, I want a lightweight append-only Trace index in addition to full Trace snapshots, so that large Runs can be summarized without loading every record.
86. As a Run inspector, I want the resolved per-Seed Run Plan stored without secrets, so that I can reproduce the exact rendered inputs and selected components.
87. As a Run inspector, I want the source Task Package snapshotted once per Run, so that provenance is preserved without duplicating authoring files for every Trace.
88. As a Run inspector, I want the full Seed, origin, digest, extracted Variables, provider settings, timing, usage, termination reason, and component versions retained by default, so that a Trace is auditable.
89. As a security-conscious operator, I want credentials and secrets excluded from persisted plans and provenance, so that inspection and sharing do not expose authentication material.
90. As a Run operator, I want artifacts stored beneath the Trace that produced them, so that generated files remain associated with their causal execution.
91. As a CLI user, I want a `validate` command, so that Task structure, Seed bindings, templates, Rubrics, capabilities, and component references can be checked without model calls.
92. As a CLI user, I want a `run` command that processes the configured Seed source or an override, so that complete generation can be started without writing Python.
93. As a CLI user, I want an `inspect` command with a compact summary and simple TUI, so that I can examine Conversations, private Tool activity, reviews, Verification, and provenance.
94. As a CLI user, I want an `export` command for native and OpenAI-style JSONL, so that recorded Traces can feed debugging and training workflows.
95. As a CLI user, I want a `reverify` operation, so that I can append a new Verification attempt to existing sealed Traces.
96. As a library caller, I want asynchronous generation as the canonical API and a synchronous convenience wrapper, so that the framework fits both services and ordinary scripts.
97. As a library caller, I want a Run Result containing Trace references and status counts, so that downstream automation can react without parsing storage files directly.
98. As a dataset curator, I want native export to support explicitly selected terminal statuses, so that rejected and failed examples remain available for analysis or negative-data workflows.
99. As a dataset curator, I want OpenAI-style dataset export to include only accepted Traces by default, so that low-quality or unverified examples cannot silently enter training data.
100. As a dataset curator, I want non-accepted statuses included only through an explicit option, so that broader exports are intentional and visible.
101. As a dataset curator, I want the default dataset projection centered on the sole Target Agent, so that the resulting Messages reflect the model being trained.
102. As a dataset curator, I want all accepted shared participant Messages in the target projection, so that the Target Agent retains the complete conversational context it actually observed.
103. As a dataset curator, I want only the Target Agent's accepted private tool calls and results in the target projection, so that another participant's hidden tools do not leak into training data.
104. As a dataset curator, I want rejected proposals, review feedback, and internal Events excluded from training Messages, so that exported examples contain only accepted behavior.
105. As a dataset curator, I want OpenAI tool-call and tool-result structures preserved with matching call identifiers, so that exported examples remain suitable for tool-capable model training.
106. As an extension author, I want built-in components selectable by short identifiers and custom components selectable by explicit import references, so that common Tasks are concise without an opaque plugin registry.
107. As a Run operator, I want component capabilities checked before generation, so that incompatible tools, message types, or model backends fail before provider spend.
108. As a Task Package consumer, I want unsafe paths, traversal, cycles, and non-portable or colliding step names rejected, so that packages remain safe and portable.
109. As a framework contributor, I want the core vocabulary to remain domain-neutral, so that patient–clinician generation can stress the system without defining healthcare-specific primitives.
110. As a framework contributor, I want generation, Review, and Verification to remain separate lifecycle concepts, so that accepted history and final dataset quality stay interpretable.
111. As a framework contributor, I want the repository initialized as a packaged library with `uv`, so that project metadata, environments, builds, and dependencies use one supported workflow.
112. As a framework contributor, I want Python 3.13 or newer to be the supported runtime, so that the implementation matches the initialized project and can use modern typing and asynchronous language features consistently.
113. As a framework contributor, I want production and development dependencies declared in `pyproject.toml`, so that dependency intent has one authoritative source.
114. As a framework contributor, I want `uv.lock` committed and checked for drift, so that local development and continuous integration resolve the same dependency versions.
115. As a framework contributor, I want project commands executed through `uv run`, so that contributors do not depend on an implicitly activated or globally modified Python environment.
116. As a framework contributor, I want a conventional `src` package layout, so that tests exercise the installed package instead of accidentally importing repository-root files.
117. As a library consumer, I want the distribution to include typing information, so that downstream editors and type checkers can understand its public API.
118. As a CLI user, I want the command installed through a standard project script entry point, so that the same CLI works from an editable checkout and an installed package.
119. As a framework contributor, I want Ruff to be the sole Python linter and formatter, so that code style, import sorting, and common correctness checks do not require overlapping tools.
120. As a framework contributor, I want Ruff configuration stored in `pyproject.toml`, so that local tooling and continuous integration enforce the same rules.
121. As a framework contributor, I want tests written and run with pytest, so that synchronous and asynchronous behavior share one familiar test workflow.
122. As a framework contributor, I want tests, linting, formatting, lockfile validation, and package building to be required checks, so that changes cannot merge with a broken development or distribution workflow.
123. As a framework contributor, I want runtime code separated from tests, documentation, examples, and throwaway prototypes, so that the published package contains only supported library behavior.
124. As a framework contributor, I want public interfaces fully type-annotated, so that Agent, Environment, Tool, Reviewer, Verifier, and storage extensions are straightforward to implement correctly.
125. As a framework contributor, I want imports to avoid network access, model initialization, filesystem mutation, and environment creation, so that library discovery and test collection are deterministic.
126. As a release maintainer, I want source and wheel distributions built through `uv`, so that the installable artifacts are verified before publication.
127. As an Agent author, I want model inference hidden behind one framework-owned asynchronous Provider protocol, so that Agent behavior is independent of vendor SDK classes.
128. As a Provider author, I want a normalized request containing Messages, function Tools, Tool choice, structured-output requirements, reasoning controls, sampling limits, and safe metadata, so that inference capabilities have one semantic contract.
129. As a Provider author, I want a normalized response containing the proposed assistant Message, private reasoning, usage, finish state, request identity, latency, and safe metadata, so that downstream lifecycle code does not parse vendor payloads.
130. As a task author, I want Provider definitions to be task-wide and referenced by model configuration, so that credentials and endpoint behavior are configured once and reused consistently.
131. As a task author, I want the OpenAI Provider to support both Responses and Chat Completions, so that I can choose the API surface appropriate for my model and deployment.
132. As a task author, I want OpenAI Responses to be the default OpenAI API surface, so that new hosted OpenAI Tasks use its current generation API unless compatibility requires Chat Completions.
133. As a vLLM user, I want Chat Completions to remain the conservative default and Responses to be selectable for a conformant server profile, so that the framework does not overstate endpoint support.
134. As a Run inspector, I want the selected Provider API Surface recorded in the Run Plan and Trace, so that the request semantics of a generation attempt are reproducible.
135. As a Run operator, I want the framework never to silently fall back between Responses and Chat Completions, so that behavior does not change without visible configuration.
136. As a Python user, I want to pass a `Pydantic.BaseModel` subclass as a structured-output contract, so that I define a typed result once and receive a validated model instance.
137. As a framework user, I want to provide explicit JSON Schema when a Python model is inappropriate, so that structured output remains portable beyond Pydantic authoring.
138. As a Run inspector, I want the normalized JSON Schema and stable fingerprint persisted without serializing the Python class object, so that structured-output provenance remains replayable and language-neutral.
139. As a framework user, I want structured output validated locally after generation, so that provider-side constrained decoding is not treated as proof of a valid result.
140. As a Run operator, I want refusal, incomplete output, invalid JSON, and schema mismatch represented as distinct typed outcomes, so that parsing failures cannot silently become ordinary Messages.
141. As a task author, I want Provider capabilities declared per API surface, so that successful conformance on one endpoint does not imply support on another.
142. As a task author, I want required Tool choice, structured output, reasoning, and combined features checked before inference when knowable, so that incompatible Runs fail before model spend.
143. As a vLLM user, I want the framework tested against a real pinned vLLM server, so that support claims cover parser, template, server-flag, and model interactions rather than only mocked wire payloads.
144. As a vLLM user, I want support for documented structured outputs, reasoning outputs, and Tool calling, so that local inference can drive participant, Reviewer, and Verifier workflows.
145. As a vLLM user, I want documented Pydantic parsing behavior supported through the OpenAI-compatible client surface, so that typed structured outputs work consistently with local models.
146. As a deployment operator, I want vLLM to remain an external server rather than a core Python dependency, so that the library does not impose GPU-specific packages on every installation.
147. As a Run inspector, I want returned reasoning stored as private model-call data rather than Conversation content, so that it cannot leak to another participant or the default Dataset export.
148. As a security-conscious operator, I want to disable full reasoning retention while preserving presence and usage metadata, so that sensitive model reasoning need not be stored.
149. As a Tool user, I want a Provider-returned Tool call treated only as a proposal, so that review, durable acceptance, assignment checks, and argument validation still occur before execution.
150. As a Run operator, I want Provider failures classified into stable typed categories, so that authentication, rate limits, timeouts, invalid requests, unsupported features, unavailable models, server errors, and malformed responses remain distinguishable.
151. As a Run operator, I want no hidden Provider retries, so that model-call counts, timing, costs, and partial effects remain auditable.
152. As a framework contributor, I want one reusable Provider contract suite for every adapter and API surface, so that semantic compatibility is proven consistently.
153. As a Reviewer or Verifier author, I want to use the same Provider and structured-output boundary as participant Agents, so that judging does not create a second inference stack.
154. As a framework user, I want the full accepted history sent on every V1 Responses request with provider storage disabled by default, so that canonical state and replay remain locally owned.

## Implementation Decisions

### Product and vocabulary

- V1 is an open-source Python library plus a thin CLI. The Python API is canonical; CLI commands delegate to it rather than implementing a second lifecycle.
- Use the domain terms in the project glossary: Task, Task Package, Seed, Variable, Run, Run Plan, Trace, Dataset, Agent Specification, Agent, Target Agent, Simulator, Task Step, Environment, Runtime, Observation, Action, Interaction, Conversation, Message Commit, Event, Tool, Reviewer, Rubric, Verifier, and Criterion.
- The framework is domain-neutral. The first stress test may instruct the built-in `user` to behave as a patient and the built-in `assistant` to behave as a clinician, but those names and rules are Task data.
- Exactly one Agent Specification per Task has `target = true`. Target status is not inferred from `user`, `assistant`, model, or tool configuration.
- `Environment` means interaction control flow. `Runtime` means where framework code and Tools execute. `local` is the only V1 Runtime.
- Rewards are not part of generation or the canonical quality model. Reviewers and Verifiers retain named Boolean evidence; normalized scores and accepted status are derived.

### Runtime and codebase requirements

- Initialize the implementation as a distributable library with `uv init --lib`. Keep the generated packaged-project structure and build-system declaration unless a demonstrated packaging constraint requires changing the build backend.
- Support Python 3.13 and newer, matching the initialized project metadata. Pin the contributor interpreter through `.python-version` and configure Ruff's target version consistently with that bound.
- Use a `src` layout for the importable package and a top-level `tests` tree that mirrors public capabilities rather than private module organization. Keep documentation, examples, research, and prototypes outside the importable package.
- Include a `py.typed` marker in the distributed package. Public classes, functions, protocols, return values, and extension boundaries must be type-annotated. A standalone static type-checker requirement may be added after the initial module shapes stabilize; Ruff is not treated as a substitute for type checking.
- `pyproject.toml` is the authoritative source for project metadata, the Python constraint, build system, CLI script entry point, runtime dependencies, development dependency group, pytest configuration, and Ruff configuration.
- Use `uv add` and `uv remove` to change runtime dependencies and `uv add --dev` for development-only dependencies. Do not maintain a hand-edited requirements file as a competing source of dependency truth.
- Commit `uv.lock`. Do not edit it manually. Local setup uses `uv sync`; continuous integration uses locked mode and fails when project metadata and the lockfile disagree.
- Run the project CLI, Python scripts, tests, and quality tools through `uv run`. Activating `.venv` may remain an editor convenience but is not part of documented or automated workflows. Never depend on globally installed Python packages.
- Register the framework CLI through the standard project script table so `uv run <command>` and an installed console command reach the same entry point.
- Add Ruff to the development dependency group and use it as both linter and formatter. Do not add Black, Flake8, isort, autoflake, or another overlapping Python formatter/linter in V1.
- Configure Ruff in `pyproject.toml`. The initial lint rule families are `E`, `F`, `I`, `UP`, `B`, `SIM`, and `RUF`, covering style errors, correctness, import ordering, Python upgrades, common bug patterns, simplification, and Ruff-specific checks. Any ignored rule must have a narrow documented reason; project-wide blanket suppression is not acceptable.
- Ruff formatting is the canonical code format. Contributors use `uv run ruff format .`; verification uses `uv run ruff format --check .`. Lint verification uses `uv run ruff check .`, while automatic fixes remain an explicit contributor action rather than a CI mutation.
- Use pytest for the test suite and `pytest-asyncio` for canonical async APIs. Tests run as `uv run pytest`; test dependencies belong to the development dependency group.
- The minimum repository quality gate is: lockfile consistency, Ruff lint, Ruff format check, deterministic tests, and successful source/wheel build. Continuous integration runs the equivalent of `uv lock --check`, `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `uv run --locked pytest`, and `uv build`.
- Production modules must not perform model calls, network access, credential loading, filesystem writes, logging configuration, or other observable setup during import. Runtime resources are created explicitly by factories or the Runner lifecycle.
- Keep module boundaries aligned with the domain model rather than providers: authoring and compilation, execution and interaction, quality, persistence, export, and CLI. Provider and custom-component adapters depend on those boundaries rather than defining them.
- Keep the runtime dependency set small. Optional integrations that introduce substantial provider- or platform-specific dependencies should be isolated behind optional extras or separate adapters rather than imposed on every library consumer.
- Package builds must produce both source and wheel distributions and must include typing metadata, required package resources, and no Run outputs, credentials, local environments, caches, research files, or prototypes.

### Task Package contract

- A Task Package has a required `task.toml` at its root. It declares schema version, Task identity, seed-source defaults, global Variable mappings, Provider and model defaults, local Runtime, Environment selection and limits, Agent Specifications, Tool references and assignments, ordered Task Steps, review policy, and final-verification policy.
- Each Agent has a conventional directory containing a required base `instruction.md`. Optional `reviewer.md` and `rubric.toml` files define its stable Reviewer prompt and base Rubric.
- A single-step Task omits the steps directory. A multi-step Task declares an ordered list of unique step identifiers and provides a directory for every step. Each step contains an agents directory with a role-specific `instruction.md` for every participating Agent and an optional `rubric.toml` whose criteria append for that step.
- There are no separate per-Agent or per-step metadata files. Structural metadata remains in `task.toml`; Markdown contains instructions; TOML Rubrics contain Criteria.
- A Verifier directory contains one optional `rubric.toml` declaring weighted Criteria and threshold, plus LLM-judge instructions or a deterministic Python implementation selected by the Task. The directory is omitted when final Verification is disabled. Reviewer Rubrics and the final Verifier Rubric remain separate concepts even though they use the same scoring rule.
- Tools are declared Task-wide and assigned per Agent for the whole Trace. Task Steps do not alter model, provider, or Tool assignments in V1.
- All package-relative paths pass a safe-resolution check. Traversal outside the package, cyclic resolution, unsafe output links, non-portable names, case-normalized collisions, duplicate identifiers, and undeclared references are validation errors.
- Package loading validates everything that is independent of a particular Seed: schema version, layout, ordered steps, Agent participation, exactly one Target Agent, component references, capability declarations, Criteria definitions, thresholds, and revision-policy consistency.
- Built-in component identifiers resolve through a small explicit Registry. Custom components use an explicit import reference. There is no implicit discovery, remote component hub, or package installation during execution.

### Seed and Variable contract

- The framework reads but does not generate Seeds. The configured source may be overridden by the CLI or replaced by a Python iterable.
- A JSON object is one Seed; each element of a JSON array is one Seed; each JSONL line is one Seed; each CSV row is one Seed. A directory contributes records from files matching its required glob, ordered by normalized path and then record position.
- `Seed` contains a stable ID, the original JSON-compatible data, source origin and record position, and a canonical digest. CSV rows are represented as flat mappings unless a custom loader explicitly produces nested data.
- `[variables]` maps unique template aliases to validated Seed selectors. Dot notation traverses nested mappings for JSON-compatible Seeds; CSV selectors address exact headers.
- The configured Seed ID field names one declared Variable alias rather than defining a second selector. When omitted, the ID is derived from a canonical content hash. IDs must be unique within a Run.
- Optional JSON Schema validation happens before Variable extraction. Every declared selector must resolve for each executable Seed, and all referenced template variables must be known.
- Jinja rendering uses a sandboxed environment with strict undefined behavior. All base instructions, Task Step instructions, Reviewer instructions that use Variables, and other seed-dependent templates are rendered before the first model call for that Seed.
- An individual record that has a stable origin but fails parsing, schema validation, Variable extraction, or rendering produces an indexed `invalid` Trace. A source-level failure that prevents reliable record enumeration fails the Run.

### Compilation models

- `TaskPackage` is unresolved authoring input. It contains the package root, parsed Task configuration, seed-source specification, Agent sources, Task Step sources, optional Verifier source, and a package content digest. It never contains live model clients, credentials, accepted history, or seed-rendered instructions.
- `Seed` remains the unmodified external record plus identity and provenance. Variable aliases are a Task-specific interpretation and do not mutate or redefine the Seed.
- The Compiler binds one prepared Task Package to one Seed and emits one immutable, serializable, secret-scrubbed Run Plan.
- A Run Plan contains schema and Task identity, the Seed, extracted Variables, resolved Provider and Agent Plans, ordered Task Step Plans, Tool Plans, Environment Plan, optional Verifier Plan, local Runtime Plan, provenance and component digests, and its own digest.
- An Agent Plan contains Agent identity, Target Agent flag, resolved model settings, rendered base instruction, assigned Tool identifiers, optional Reviewer Plan, and base Rubric.
- A Task Step Plan contains the step identity and one rendered step-specific instruction plus appended Rubric for every Agent.
- A Provider Plan contains the Provider identity and type, selected Provider API Surface, model-facing non-secret connection settings, typed provider options, a per-surface capability profile, and secret references rather than resolved secret values.
- A Structured Output Plan contains the stable schema name, normalized JSON Schema, strictness and description metadata, optional qualified Python type name for provenance, and canonical schema fingerprint. The originating class object remains runtime-only.
- A Run Plan contains no live Agents, Environment instance, recorder, Conversation, model response, Tool result, or Verification result.
- Component construction and preflight happen only after successful compilation, ensuring static and Seed-dependent configuration failures occur before provider spend.

### Provider and structured-output contract

- `Provider` is a framework-owned asynchronous protocol with a capability property, one semantic `generate` operation, and asynchronous cleanup. Vendor SDK request and response classes never cross this boundary.
- Agents construct semantic Provider requests from Observations. Providers translate requests and responses, normalize usage and metadata, and classify inference failures. Providers do not own Conversation state, Tool execution, review, revision, scheduling, persistence, or Verification decisions.
- The normalized request includes a model identifier, ordered OpenAI-style Messages, function Tool definitions, Tool choice, optional Structured Output Schema, optional reasoning controls, sampling and token limits, trace-safe metadata, and narrowly typed provider-specific options.
- The normalized response contains exactly one proposed assistant Message, optional private reasoning, an optional locally validated typed result, finish or incomplete state, provider and model identity, normalized usage, request identity, latency, and secret-scrubbed metadata.
- The two V1 Provider API Surfaces are `responses` and `chat_completions`. The selected surface is explicit in the compiled Provider Plan, immutable for a Trace, and recorded in provenance. Providers never silently fall back between them.
- The built-in OpenAI Provider defaults to Responses and may explicitly use Chat Completions. Generic OpenAI-compatible and vLLM profiles default conservatively to Chat Completions; Responses is available only when the declared endpoint profile has passed that surface's conformance requirements.
- Both surfaces map to the same semantic request and response. Responses output items and Chat Completions choices are normalized into framework Messages, Tool calls, private reasoning, structured results, and typed non-success states.
- V1 sends the complete accepted history with each request, does not make `previous_response_id` authoritative, and disables provider-side storage by default. The Trace remains the source of truth for state and replay.
- Portable Tools are function Tools only. Provider-hosted Tools that may perform effects before the framework review boundary are not supported in V1.
- Structured-output APIs accept either a `Pydantic.BaseModel` subclass or an explicit framework JSON Schema specification. Pydantic V2 is a required core dependency.
- A Pydantic class is normalized with `model_json_schema()` during compilation. The resulting schema and fingerprint are serializable; the class itself is retained only at runtime for local validation and typed result construction.
- The adapter may use an API surface's native parsing helper, including OpenAI-compatible Pydantic parsing, but local validation against the framework-owned schema or original Pydantic class is mandatory. Refusal, truncation, incomplete output, invalid JSON, and schema mismatch are handled before a typed value is exposed.
- Provider capabilities are declared per API surface and cover text, supported Tool-choice modes, multiple or parallel Tool calls, JSON object and JSON Schema output, Pydantic round trips, reasoning extraction and controls, provider-native extensions, and future streaming support.
- The Compiler derives required capabilities from Agents, Reviewers, Verifiers, Tools, structured-output settings, and reasoning settings. Known incompatibilities fail preflight; endpoint contradictions become typed unsupported-feature, invalid-request, or malformed-response failures.
- vLLM is accessed through a separately managed OpenAI-compatible server. Its profile supports the documented structured-output, reasoning-output, and Tool-calling features only for tested combinations of vLLM version, model revision, parser flags, chat template, server configuration, API surface, and hardware class.
- vLLM-native structured modes and reasoning controls use typed options rather than an unrestricted extra-body mapping. Server parser flags are configuration and provenance, not framework secrets or guessed defaults.
- Reasoning stays outside Message content and accepted Conversation history. It is participant-private Event data, excluded from relay and default training export, and retained by default unless an explicit policy suppresses the full text.
- A returned Tool call remains a model proposal. Provider shape validation does not replace active Rubric review, durable Message Commit, Agent assignment validation, Tool argument validation, or the review-before-effect rule.
- Provider failures use stable categories for authentication, authorization, rate limiting, timeout, network, invalid request, unsupported feature, unavailable model, provider server error, malformed response, and unknown failure. V1 performs no automatic Provider retry.
- Provider clients may pool stateless transports across Traces, but every request is self-contained and all trace-bound mutable state remains isolated. The Runner owns Provider cleanup.

### Runner and Environment contract

- One `Runner.run(TaskPackage)` invocation opens one Run, deterministically enumerates all selected Seeds, compiles and executes one Run Plan per valid Seed, and finalizes a collection result.
- V1 processes Seeds sequentially. It continues after a Seed-specific invalid, failed, unverified, or rejected Trace unless fail-fast was explicitly requested.
- Every Trace receives fresh trace-bound Agent, Interaction, Tool-context, Reviewer-state, Environment, and recorder instances. Provider transports may pool stateless resources internally, but no accepted history or mutable execution state crosses Trace boundaries.
- The Environment protocol exposes asynchronous `setup(agents)`, `run(task_context, agents)`, and optional `finalize(task_context, trace_snapshot)` operations. The Runner owns timeouts, lifecycle state, cleanup, error classification, persistence, and Verifier dispatch around these hooks.
- `TaskContext` is an immutable projection containing Task and Seed identity, extracted Variables, ordered Task Steps, termination limits, and controlled Task Step activation. It excludes credentials, storage internals, raw provider clients, and final-Verifier policy.
- Environment implementations receive run-bound Agent facades. They cannot append raw Conversation Messages or bypass an Interaction's review and persistence rules.
- The built-in dialogue Environment expects the generic `user` and `assistant` participants, opens an Interaction for both, asks the configured initiator for the first accepted reply, and then alternates accepted replies until termination or truncation.
- The built-in single-agent Environment uses the same Interaction boundary without a simulator.
- Custom Environments may implement different multi-party control flow directly in Python. Task configuration does not define a generic turn-order list, routing graph, parallel branch, or wake-up policy.
- Legitimate task completion produces a terminated generation outcome. Maximum rounds, timeouts, provider failures, Tool failures that cannot be represented as results, reviewer exhaustion without a permitted fallback, and other incomplete endings produce truncation or failure with a typed reason.
- When Task Steps are present, the framework provides controlled step-advance and completion actions to the Target Agent and Environment. These remain structurally valid model Messages and pass the same review-before-effect boundary as other model-produced tool-call Messages.

### Message and Interaction contract

- `Message` follows the OpenAI message shape: role, content, optional name, optional tool calls, and optional tool-call identifier. The native model adds a stable Message ID and `actor_id` so peer participants can be represented without losing source identity.
- An Agent consumes an Observation and available Tool declarations and returns one Message or an ordered list of Messages. The framework processes a list at Message boundaries rather than treating it as one opaque review subject.
- An Observation includes the Agent's rendered base instruction, its active Task Step instruction, every accepted shared conversational Message in canonical order, and only that Agent's accepted private tool-call and tool-result Messages.
- The Conversation is one canonical ordered stream for the entire Trace and survives Task Step transitions. It contains accepted Messages only.
- The Event stream contains proposals, raw model calls, Reviewer requests and results, rejections, revisions, usage, timing, execution metadata, failures, and lifecycle transitions. Events never become model-visible accepted history.
- `Interaction.turn(incoming=None)` is the deep execution operation. It constructs the Observation, invokes the Agent, conducts private Tool and review loops, commits accepted Messages, and returns a typed result containing the accepted outbound reply reference and termination state.
- An incoming reply is a reference to an already persisted Message. Relaying it changes the receiving participant's projected Observation but does not append a duplicate Message.
- Only an accepted outbound conversational Message is returned to the Environment for relay. A rejected proposal is never visible to another participant.

### Reviewer, Tool, and Message Commit state machine

- Every model-produced Message is reviewed independently when Review is enabled. This includes a normal conversational Message, a Message containing one tool call, or a Message containing multiple tool calls.
- The active Rubric is the Agent's base Criteria plus the current Task Step's appended Criteria. Composed Criterion IDs must be unique and weights must be finite and positive with a positive total.
- The Reviewer returns a complete `criterion_id -> Boolean` mapping plus feedback. The framework validates the mapping and computes `passing weight / total weight`. The Message passes when that score meets the configured Reviewer threshold in the inclusive range zero to one.
- `max_revisions` means the number of additional proposals allowed after the initial rejected proposal. Every revised model Message crosses the complete review boundary again.
- `accept_on_revision_exhaustion` is disabled by default and must be explicitly enabled. It applies only to an outbound conversational Message, which is committed with `review_exhausted = true`. It never applies to a tool-call or control-action Message.
- A Message containing multiple tool calls is reviewed once as the model produced it. After acceptance, V1 executes those calls sequentially in declared order; parallel Tool execution is not supported.
- Tool arguments are validated against the input schema before execution. Each returned result is validated against the Tool result contract or optional output schema and persisted as a matching OpenAI-style tool-result Message.
- Tool results are not model proposals and therefore are not LLM-reviewed. A Tool execution failure is captured as a typed Tool result when the Tool protocol can represent it, or fails the Trace when it cannot.
- `MessageCommit` is the atomic durable Conversation operation. It stores one accepted Message with stable Message, turn, Task Step, Agent, visibility, review, and causal references.
- The following state sequence is normative and was validated in the interactive prototype:

```text
model proposes tool-call Message
  -> Reviewer scores tool-call Message
     -> below threshold: record rejection Event; do not execute; request revision
     -> threshold reached: commit private tool-call Message
        -> execute and validate Tool
        -> commit private tool-result Message
        -> Agent observes accepted private exchange and proposes next Message
           -> Reviewer scores outbound conversational Message
              -> below threshold: record rejection Event; request revision
              -> threshold reached: commit shared Message; relay to next Agent
```

- A process failure may leave a valid partial Conversation ending with an accepted tool-call or tool-result Message and no outbound reply. The Trace is retained as failed rather than rolling back durable accepted history.
- Tool privacy is enforced by Observation and export projection, not by splitting canonical occurrence order into separate Conversations.

### Final Verifier contract

- The final Verifier runs only after Environment execution and finalization have completed and the generation Conversation has been sealed.
- Deterministic Python Verifiers and LLM judges implement one asynchronous protocol over an immutable Trace Snapshot.
- Verifier configuration declares uniquely identified Criteria, a positive weight for every Criterion, and a normalized threshold. The Verifier returns exactly one Boolean for every declared Criterion.
- Missing, duplicate, unknown, non-Boolean, or otherwise malformed verdicts are Verifier errors. An exception, timeout, or malformed judge response must not be converted into false criteria.
- The framework computes the normalized score by summing weights for true verdicts and dividing by total declared weight. A valid result at or above threshold marks the Trace `accepted`; a valid result below threshold marks it `rejected`.
- A Verifier execution or validation failure marks a generated Trace `unverified` without changing its sealed Conversation.
- Reverification appends a new immutable Verification attempt. It does not regenerate, delete, or rewrite accepted Messages. Export eligibility is derived from the selected or latest valid Verification result.

### Persistence and status model

- Run identity refers to one Task invocation over a Seed source. Seed identity refers to the logical input. Trace identity refers to one execution attempt for one Seed. Task Step identity refers to an instruction phase. Turn identity groups Messages from one participant interaction but is not a persistence transaction.
- Generated run and Trace IDs are distinct from content digests. The Task Package, Seed, Run Plan, components, and relevant source material retain separate digests.
- A Run stores one immutable source Task snapshot, a manifest with versions, timings and status counts, and an append-only Trace index containing summary metadata and the location of each full Trace.
- Each Trace stores its rendered secret-scrubbed Run Plan, a Trace manifest, accepted Conversation as Message Commit records, Events, versioned Verification attempts, and artifacts.
- The full Trace directory—not the Run's Trace index—is the canonical source for inspection, re-verification, and export.
- Before advancing to the next Seed, the Runner durably finalizes that Seed's complete available Trace snapshot and appends or updates its index reference.
- Once a source record has a stable origin, its attempt is retained even if it is invalid or fails before a model call. The status set is `invalid`, `failed`, `unverified`, `rejected`, and `accepted`.
- Generation outcome is also recorded independently as terminated, truncated, or failed with a reason. This prevents final quality status from erasing how interaction execution ended.
- Persistence uses append-safe or atomic-replace operations so a crash cannot expose a successfully indexed Trace whose referenced snapshot was never made durable.
- Persist the full Seed by default together with origin, Variables, selected models and inference settings, Tool and component identities, package and Python versions, usage, timing, and termination reason. Never persist provider credentials or secret configuration values.
- Automatic infrastructure retries and resume from a partial Trace are not implemented in V1. A rerun creates a new Trace ID and retains the same Seed ID.

### Export and inspection

- Native export serializes complete Trace snapshots and supports explicit selection by Run, Trace, Seed, and terminal status.
- OpenAI-style JSONL is the initial training export. By default it includes only Traces whose selected Verification result is accepted.
- Including rejected, unverified, invalid, or failed Traces requires an explicit option. Invalid Traces without a usable Conversation remain native records and do not become empty training examples.
- Default training projection is centered on the sole Target Agent. Target-authored conversational and tool-call Messages map to assistant Messages; accepted conversational Messages from other participants map to user Messages; matching target-owned Tool results map to tool Messages.
- The projection includes all accepted shared conversational Messages and only the Target Agent's private accepted tool-call and tool-result Messages. Simulator-private Tool exchanges are excluded.
- Tool-call arguments remain structured JSON and Tool results retain the matching `tool_call_id`. Rejected proposals, Reviewer feedback, internal Events, and private execution metadata are excluded from training Messages.
- The `inspect` experience includes a non-interactive summary and a simple terminal UI. It can switch among accepted Conversation, participant projections, review attempts, Verification, provenance, errors, and artifacts without mutating the Trace.
- Export and inspection read persisted Trace snapshots rather than in-memory Runner objects, proving that the recorded artifact is sufficient for downstream use.

### Public interfaces and error behavior

- The main library entry point loads a Task Package and asks a Runner to process it. Convenience `generate` and `generate_sync` functions may wrap this path but cannot introduce different semantics.
- The returned Run Result contains Run identity, ordered Trace references, and counts for invalid, failed, unverified, rejected, and accepted statuses.
- The CLI provides `validate`, `run`, `inspect`, `export`, and `reverify`. Command output is concise by default and supports machine-readable status for automation.
- Extension code may raise normal exceptions. Framework boundaries classify them into package, Seed, compilation, provider, Agent, Reviewer, Tool, Environment, persistence, or Verifier failures and preserve causes in Events.
- A Task-wide or source-enumeration error fails the Run because executable work cannot be identified reliably. A Seed-specific or Trace-specific error remains scoped to that Trace unless fail-fast is active.
- No automatic retry hides a provider, Tool, Reviewer, Environment, or Verifier failure. Reviewer-directed revision is domain behavior and is not an infrastructure retry.

## Testing Decisions

- Repository verification starts from a clean locked environment. The supported local sequence is `uv sync`, followed by all commands through `uv run`; continuous integration additionally rejects lockfile drift with `uv lock --check` or locked execution.
- Every change must pass `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `uv build`. These are release requirements, not optional contributor conveniences.
- Test collection and importing the top-level package must cause no network access, model construction, storage creation, or filesystem mutation.
- The primary acceptance seam is the public `Runner.run(TaskPackage)` lifecycle using a temporary Task Package, deterministic fake Agents, Reviewers, Tools, Environment where necessary, Verifier, and local Run Store. Assertions inspect only the returned Run Result, persisted Trace snapshots, public inspection model, and exported Dataset—not internal call order or private helper state.
- This one high-level seam must cover package loading, per-Seed compilation, strict rendering, Environment control flow, Message review, Tool execution, Message Commit persistence, final Verification, multi-Seed continuation, terminal status counts, and export projection.
- Deterministic test components return scripted OpenAI-style Messages and verdicts. They are protocol-faithful extensions rather than mocks of internal methods, keeping tests valid if internal modules are reorganized.
- A complete success scenario processes at least two Seeds and proves one independent Trace per Seed, fresh Agent state, retained history across two Task Steps, accepted private target Tool activity, accepted shared replies, passing Verification, and accepted-only OpenAI export.
- A review scenario proves a rejected tool-call Message is recorded as an Event, is absent from accepted history, and does not execute; a revised accepted call is committed before execution; its result is private; a separately rejected and revised conversational draft is not relayed until accepted.
- A threshold scenario uses mixed weighted Boolean verdicts to prove framework-derived Reviewer and Verifier scores, inclusive threshold comparison, and independence of the two thresholds.
- A malformed-review scenario proves missing, unknown, duplicate, or non-Boolean Criterion output cannot commit a Message or execute a Tool.
- A revision-exhaustion scenario proves explicit fallback can accept only a conversational draft, marks that Message or turn as review-exhausted, and never force-executes a rejected Tool call.
- A privacy scenario inspects Observations or public participant projections to prove both Agents see shared accepted Conversation history while only the invoking Agent sees its Tool calls and results.
- A persistence-failure scenario stops after an accepted Tool call or result and proves the failed Trace retains the durable partial Conversation, Events, and failure reason but is excluded from default Dataset export.
- A Task Step scenario proves base instructions remain, only the current step's additions and Criteria are active, previous step additions expire, and all accepted Conversation and private Tool history remain.
- A Seed-source scenario covers a JSON object, JSON array, JSONL, CSV, directory glob ordering, Python iterable, stable configured ID, content-hash fallback, duplicate IDs, nested dot paths, flat CSV headers, and optional schema failure.
- A collection scenario proves invalid, failed, unverified, rejected, and accepted Seed attempts are all indexed with correct Run counts and that processing continues unless fail-fast is selected.
- A Verifier scenario proves a valid false verdict produces rejection, while exception, timeout, incomplete mapping, unknown Criterion, and malformed verdict produce `unverified`. Reverification must append a result without changing Conversation bytes.
- An export scenario proves native export can include explicitly selected statuses, default OpenAI export includes only accepted Traces, explicit inclusion is required for other statuses, and the Target Agent projection excludes Simulator-private Tools and all rejected proposals.
- A provenance scenario proves the source Task snapshot, rendered Run Plan, full Seed and origin, component digests, model settings, versions, timing, and termination reason are available while injected credentials are absent.
- A package-safety scenario proves path traversal, unsafe links, duplicate or colliding identifiers, missing Agent step instructions, invalid target cardinality, unsupported capability combinations, and undeclared components fail before any scripted model call.
- A termination scenario distinguishes legitimate termination from maximum-round truncation, timeout, provider error, Tool failure, Environment failure, and review exhaustion.
- Custom extension contract tests cover Agent, Environment, Tool, Reviewer, and Verifier protocol conformance at their public boundaries. They must not duplicate lifecycle assertions already proven through the Runner seam.
- A reusable Provider contract suite runs against deterministic fake transports for every adapter and declared API Surface. It covers plain text, ordered Message normalization, Tool definitions and Tool-choice modes, single and multiple Tool calls, structured outputs, reasoning separation, usage and request metadata, typed failures, secret scrubbing, and asynchronous cleanup.
- Provider semantic-parity tests submit equivalent requests through Responses and Chat Completions and assert equivalent framework Messages, parsed values, reasoning separation, and failures without requiring identical vendor payloads.
- Structured-output tests cover explicit JSON Schema and Pydantic models with nesting, collections, enums, aliases, nullable fields, and forbidden extras; stable fingerprints; refusal and incomplete states; invalid JSON; schema mismatch; unsupported schema constructs; and equivalent validated result types across both API Surfaces.
- vLLM support includes an opt-in real-server conformance suite in addition to deterministic core tests. It records the pinned vLLM version, model revision, API Surface, server flags, reasoning and Tool parsers, chat template, hardware class, and request profile.
- A vLLM release claim requires the tested surface to pass plain generation, Pydantic-backed structured output, separated reasoning, automatic function Tool calling, Tool-result continuation, and each claimed combined-feature case. Chat Completions conformance does not imply Responses conformance.
- The thin CLI receives smoke tests for argument parsing, exit status, override forwarding, and delegation for `validate`, `run`, `inspect`, `export`, and `reverify`. Business behavior remains asserted through the library seam.
- The inspection TUI receives a minimal rendering/navigation test over a recorded fixture. It is not tested through terminal implementation details or pixel snapshots.
- Tests must not call live model providers, external Tools, or network services. A separately configured integration suite may exercise real provider adapters without being required for the deterministic core test suite.
- Ordinary CPU pull-request checks do not require a live vLLM server or GPU. Real vLLM conformance may run in an opt-in environment, but must pass before a release claims compatibility with that pinned profile.
- There is no existing implementation-test prior art in the repository. The interactive prototype is prior art for state-transition scenarios, and the ADR lifecycle examples are the behavioral oracle until executable tests establish the contract.

## Out of Scope

- Generating, augmenting, balancing, or curating Seeds.
- A hosted control plane, web dashboard, collaborative annotation product, or production version of the interactive prototype.
- Docker, sandbox, remote, distributed, or cloud Runtimes; `local` is the only V1 Runtime.
- Concurrent Seed execution, vectorized Environments, parallel sampling, or parallel Tool execution.
- Model routing, provider failover, ensemble policies, branching workflows, or declarative turn graphs.
- Background, scheduled, sleeping-conversation, reminder, or unsolicited participant Messages.
- A built-in Environment for more than two dialogue participants. Custom Environments remain able to express other protocols.
- A public Gym, PettingZoo AEC, OpenEnv, MCP, Open Reward Standard, or ATIF compatibility layer.
- Scalar rewards, reinforcement-learning credit assignment, online training, or optimizer integration.
- Automatic infrastructure retries, checkpoint resume, or continuation of a partial Trace.
- Cross-Seed Agent memory or shared mutable conversation state.
- Per-step model, provider, Tool, Runtime, or Environment overrides.
- Arbitrary per-Message visibility declarations; V1 visibility is shared conversational history or invoking-Agent-private Tool history.
- Reviewing framework-produced Tool results with an LLM. Results are validated by their Tool contract.
- Streaming Provider responses, partial-message review, and streaming export.
- Provider-hosted Responses Tools such as web search, file search, computer use, or remote MCP, because their effects can occur before the framework reviews a Tool-call Message.
- Provider-owned authoritative conversation state or replay through `previous_response_id`.
- Automatic promotion of rejected or unverified data into training exports.
- Remote component registries, plugin marketplaces, implicit imports, or dependency installation during a Run.
- Domain-specific patient, clinician, clinical-safety, consent, de-identification, or privacy-policy primitives. Those policies can be expressed by Tasks, Reviewers, Tools, and Verifiers or added by downstream consumers.
- A guarantee of exact replay against nondeterministic external model providers. V1 guarantees recorded provenance and immutable artifacts, not provider determinism.
- Performance optimization beyond deterministic sequential execution and bounded resource use.

## Further Notes

- ADR-0002 is authoritative for the Environment authoring surface and generic `user`/`assistant` roles. ADR-0003 is authoritative for Run, Seed, Trace, Task Package, Run Plan, and collection cardinality. ADR-0004 is authoritative for per-Message review, review thresholds, Tool execution order, Message Commit persistence, and complete terminal Trace export. ADR-0005 is authoritative for the framework-owned Provider boundary, typed capabilities and failures, private reasoning, and vLLM conformance. ADR-0006 is authoritative for Responses and Chat Completions, per-surface capabilities, Pydantic structured outputs, and local state ownership. ADR-0001 remains the source for retained Task Package, templating, Tool, CLI, and verification decisions not amended by later records.
- The framework should feel like Harbor during authoring, validation, inspection, provenance, persistence, and reverification, and like Prime Intellect Verifiers when Environment authors orchestrate Agents through Interactions. Its differentiator is the accepted-data boundary and participant-aware export, not a copy of either upstream object model.
- The interactive prototype is throwaway design evidence, not production UI or an implementation base. Its useful output is the reviewed-Message state machine and the demonstrated distinction among Run index entries, complete Trace snapshots, and Dataset projections.
- A sensible implementation order is: domain models and validation; Task Package and Seed compiler; Run Store and Message Commit recorder; Agent/Interaction and deterministic adapters; Reviewer and Tool loops; built-in Environments; final Verifier and reverification; exporters; thin CLI and TUI.
- The first vertical slice should run one tiny single-step dialogue Task over one Seed using deterministic Agents, persist a complete accepted Trace, verify it, and export it. Subsequent slices should add rejected reviews, Tools, multiple Task Steps, multiple Seeds, failure statuses, the semantic Provider protocol, the two API surfaces, Pydantic structured outputs, and vLLM conformance without changing the public lifecycle seam.
- The distribution and import package are named `agentinstruct`. The concrete serialization library beyond required Pydantic models, standalone static type checker, logging library, and release milestone remain intentionally undecided and may be selected during implementation without altering this specification's public behavior.
- The development workflow follows the official `uv` packaged-library, locking, syncing, running, and building model and the official Ruff linting and formatting model. Revisit exact tool versions through normal lockfile updates rather than weakening reproducibility by using floating global installations.
