# 05b: Concrete Agent, Environment, and Episode

Type: implementation
Status: resolved
Blocked by: 05
Date: 2026-10-02

## User direction

Agent directly owns instruction, model, Tools and Reviewer. Remove AgentPlan and Interaction, including the empty interaction context. A conversational Environment owns two Agents; one recorded episode holds their accepted conversation. Use the linked verifiers Env/Episode/UserSim scheduling idea while keeping local implementation lean.

## Bounded slices within this replacement

1. Agent ownership (`execution.py`, remove `model_agent.py`): combine generation/Review/Tools and direct turn/control calls; remove ScriptedAgent and Agents wrapper.
2. Episode ownership (`store.py`, remove `steps.py`): merge recording, shared step state and snapshot construction; no Episode wrapping another recorder.
3. Frozen authoring evidence (`plans.py`, `task_package.py`): delete AgentPlan, retain the existing nine saved Agent JSON fields, and freeze them once without storing live Agents/clients.
4. Assembly and exports (`runner.py`, `components.py`, `__init__.py`): instantiate actual Agents, Environment-owned mapping, Episode; retain preflight/resource/sealing/final Verification behavior.
5. Caller migration: update active factories/Environments/examples in bounded groups, with no retired-name forwards. A proposal callback remains an actual extension seam for custom generation; it does not own a second acceptance loop. AgentTool's isolated one-shot draft contract remains.
6. Validate behavior and document the new interface; then stop at the code-review checkpoint before Task 06.

These are dependent source/migration slices of one user-authorized replacement, not permission to implement later authoring/seed/quality refactors. Record each slice's changed files and verification in the Answer; keep constructor changes and active callers together for the final reviewable checkpoint.

## Acceptance

- [ ] Concrete Agent holds requested attributes and owns generation/Review/revision/Tool acceptance.
- [ ] No AgentPlan, Interaction, ModelAgent, ScriptedAgent, Agents wrapper, TraceRecorder or StepProgress implementation/alias remains.
- [ ] Environments own their actual Agents, schedule direct turns and record one episode; custom hooks migrate explicitly.
- [ ] Task syntax and historical saved JSON remain readable; compile/validate never construct live components.
- [ ] Agent Review authorizes messages before effects; final Verification remains independent and observes sealed evidence.
- [ ] All existing safety behaviors and appropriate offline gates pass; publish actual deletions separately from relocation.

## Answer

Superseded before completion by the user's stricter deletion request in [05c](05c-remove-plans-and-lean-task-loop.md). Intermediate Plan/ToolContext/AgentTool/factory retention was rejected. No full checkpoint is claimed for 05b.
