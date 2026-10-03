---
status: accepted
date: 2026-10-03
implementation: implemented
amends:
  - ADR-0026
---

# Restore Runner to the Task loop

The user explicitly rejected Runner's lifecycle expansion in commit 5367d23 and
pointed back to the library design specification and ADR-0012. Simplification did
not authorize moving deadlines, failure policy, sealing and judgment into Runner.
The original responsibility split is restored.

Runner owns output_dir and only loops over prepared Tasks: open each existing
Episode at output_dir / episode.id, await Environment.run(task, client=...), and
collect that Episode. It forwards custom Environment errors directly and does
not interpret Task limits or judge settings. Open/recording failures remain
explicit. There is no lifecycle wrapper or new runtime owner.

Environment owns Task execution and finalization. The default UserSimEnv begins
recording after registering borrowed-client secrets, applies the Task deadline,
executes segments, records outcomes, seals generation and invokes the optional
final Evaluator. Episode retains durable recording and verification invariants.
Required safeguards stay together with their actual execution owner. Custom
Environment implementations choose and implement their own execution policy.

Keep the one-method structural Environment interface, Generator/Evaluator seams,
ready Task evaluators and application-owned clients/resources from ADR-0026.
Domains can supply generators/evaluators to UserSimEnv to retain its safeguards.
Standalone UserSimEnv execution works after the caller opens task.episode.
Generic resource stacks, cleanup managers, verifier assembly and duplicate model
preflight remain removed. No constructor/factory layer is added to Runner.

Runner now has only __init__ and run, with no private helpers. Behavioral tests
prove ordered calls, stable Episode identity, shared-client forwarding and that
Runner does not apply execution policy around custom Environments. Standalone
Environment tests preserve deadlines, failure recording and final verification;
the existing cancellation, privacy, durable Tool intent and SDK checks remain.
