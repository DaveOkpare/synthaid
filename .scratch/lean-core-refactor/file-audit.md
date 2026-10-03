# File audit: lean-core refactor

Date: 2026-10-02

Audit each file before changing it: identify production/CLI/task-selected/public-extension callers, then inspect every defined class/function. Remove wrappers and dead paths; simplify duplication; retain behavior with real callers. Tests alone do not justify a compatibility alias. Record actual deletion separately from relocation.

## Task 05: execution.py

Decision: retain the execution boundary; delete `AgentHandle` and its constructor. Its only job was constructing/yielding `Interaction`. The existing Interaction now yields itself from `interaction(task)`, and Runner constructs it directly. No new class or alias.

| Definition | Decision and actual responsibility |
| --- | --- |
| Observation | Keep: input to custom/Model/Scripted Agents and AgentTool. |
| Agent.generate | Keep: active proposal-producer extension contract. |
| ScriptedAgent.__init__, generate | Keep: task-selected `scripted` implementation, offline generation. |
| create_agent | Keep: Runner's built-in/explicit-reference construction path. Assembly reviewed in Task 06. |
| TaskContext.__post_init__ | Keep: immutable variables and ordered step IDs for Environments. |
| TaskContext.advance_step, complete_task | Keep: custom Environments propose reviewed controls without recorder mutation. |
| TurnResult | Keep: accepted reply/termination contract consumed by Environments. |
| AgentError.__init__ | Keep: Runner distinguishes malformed proposals from execution errors. |
| Interaction.__init__ | Keep: one per-Agent owner of producer, Reviewer, Tools, progress, recorder and counters. |
| Interaction.interaction | Keep: existing Environment context-manager hook; now yields this same owner. |
| Interaction._generate | Keep: proposal generation, feedback delivery and durable failure diagnostics. |
| Interaction._instruction | Keep: base instruction plus active-step instruction. |
| Interaction._observation | Keep: accepted shared history plus invoking Agent's private Tool exchanges. |
| Interaction._event | Keep: durable events with step/actor/turn identity and cancellation/persistence handling. |
| Interaction._proposal, _proposal_error | Keep: normalize proposals and record categorized failures. |
| Interaction._validate_proposal | Keep: message/Tool/control shape, call-ID uniqueness, actor assignment and safe normalization. |
| Interaction._review | Keep: invokes this Agent's Reviewer with active rubric; validates verdicts; records acceptance/rejection. |
| Interaction.turn, control | Keep: active Environment hooks, both use the same acceptance loop. |
| Interaction._turn | Keep: per-message revision budgets, accepted incoming replies, durable intent before effects, Tool continuation and completion. |
| Interaction._execute_tool | Keep: assignment/schema/result checks, private results, controls, execution-error policy and durable failures. |
| AgentHandle.__init__, interaction | Remove wrapper class/constructor; move the active context-manager hook onto Interaction. No alternate implementation. |
| Agents.__init__, __getitem__, __len__, __iter__ | Keep: readonly Mapping presented to built-in/custom Environments. Values are now the single Interaction owner. |
| Environment.setup, run | Keep: active scheduling extension contract. |
| FinalizingEnvironment.finalize | Keep: typed optional finalization invoked by Runner before sealing/Verification. |
| SingleAgentEnvironment.setup, run | Keep: task-selected single-Agent scheduling/limits. |
| DialogueEnvironment.__init__, setup, run | Keep: task-selected two-Agent ordering, accepted-reply relay and limits. |
| create_environment | Keep: task-selected built-in/explicit-reference construction. Assembly reviewed in Task 06. |

Private method callers are within Interaction; its turn/control/context hooks are called by built-in Environments, custom Environments in examples/tests, and Runner's constructed Agents mapping. Runtime safety bodies are unchanged rather than redistributed into new modules.

## Task 05: review.py

All 86 lines remain active; a separate contract file does not add a workflow phase. Interaction owns and invokes its Reviewer.

| Definition | Decision and caller |
| --- | --- |
| ReviewRequest, ReviewResult | Keep: custom Reviewer contract and Interaction's local validation. |
| Reviewer.review | Keep: injected/task-selected Reviewer extension method. |
| ModelReviewer.__init__, review | Keep: Runner constructs this per Agent; delegates actual inference to QualityCall. |
| ReviewExhausted | Keep: Interaction raises it; Runner records exhausted-review failure. |
| ReviewError.__init__ | Keep: Interaction classifies execution/malformed verdicts; Runner records failure reason. |
| DeterministicReviewer.__init__, review | Keep: explicit built-in selector in components.py, offline Tasks. |
| create_reviewer | Keep: Runner default/injected-factory seam and task-selected construction. |

## inspection.py

See [the full class/function inventory and reduction candidates](inspection-audit.md). Its saved-Run reader is used by export as well as inspection; its display responsibilities can be assessed separately.

## Next audit

Task 06 audits Runner's construction/preflight and cleanup boundaries. Authoring validation, model-call evidence and Seed preparation follow their existing tickets. Inspection candidates remain a reviewable planning result until a separate implementation slice is authorized.
