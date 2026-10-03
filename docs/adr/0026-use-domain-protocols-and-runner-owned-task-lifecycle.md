---
status: accepted
date: 2026-10-03
implementation: implemented
amends:
  - ADR-0012
  - ADR-0015
  - ADR-0016
  - ADR-0025
---

# Use domain protocols and a common recorded Task lifecycle

The user requested a verified checkpoint commit, followed by a deeper, simpler
Python design using protocols across domains. They identified Environment's
resource/configuration machinery as unnecessary. Checkpoint 6de2613 preserves
that earlier implementation and its verification.

Environment becomes a one-method structural protocol: async run(task, *, client).
It expresses domain work into a prepared Episode. The default stateless UserSimEnv
activates segments and schedules assistant/user Agents. Runner accepts an instance,
begins recording, enforces the Task deadline, seals generation and runs final
verification. This replaces the earlier constructor-bound Environment and thin
Runner loop explicitly, rather than retaining parallel lifecycle paths.

Delete Environment's generic resources/context-stack/shielded-cleanup machinery,
verifier dictionary assembly, duplicate model preflight and parallel failure
finalization. Applications own external contexts and initialize model clients.
Custom implementations honor cancellation and own their domain dependencies.
The default UserSimEnv owns no external resources to clean up. Launcher process
ownership remains with the launcher; SDK clients remain borrowed throughout.

Generator and Evaluator are structural protocols with one method each. Agent
wraps a supplied generator with proposal validation, revision, durable approval
and Tool execution. Evaluators return validated Judgment values; reviewer and
verifier placements choose their invocation inputs. Built-in Agent/Judge remain
usable, and plain domain adapters require no inheritance or SDK attributes.
Task/Episode stay concrete data owners. No generic registry, service container,
new runtime owner or mirrored implementation hierarchy is introduced.

Task carries prepared Agents and evaluators; authoring translation belongs in the
optional loader. Task declarations describe its data, and its roles derive from
its existing initiator/participants. Root imports remain the same seven names.
Every shipped function still stays below 20 inclusive physical lines.

This refines previous ownership decisions under the user's new instruction.
Migrations are in docs/migration-seven-modules.md; verification and exact counts
are in .scratch/deep-modules/implementation.md. Historical JSON remains readable.
