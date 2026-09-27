---
status: accepted
date: 2026-09-23
supersedes: ADR-0001
---

# Use run-based environments and generic user–assistant roles

> Amended by [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md), which reviews tool-call messages before execution and replaces bundled turn commits with incremental accepted-message commits.

ADR-0001 selected a public Gym/PettingZoo-style `current_agent`/`observe`/`step` protocol. We will instead follow the simpler control-flow pattern demonstrated by Prime Intellect's `UserSimEnv`: an environment implements `run(task, agents)`, opens an interaction for each agent, and relays accepted replies between them. The built-in dialogue roles are the domain-neutral `user` and `assistant`; healthcare and other domain identities belong in task instructions and seed data rather than framework types.

This ADR supersedes ADR-0001 as the current architectural record. Its changes are limited to environment execution, turn processing, and dialogue-role naming. ADR-0001's decisions about task packages, steps, seeds and variables, review, final verification, native traces, persistence, tools, and CLI/API entry points remain adopted.

## Decision

### Environments own ordinary Python control flow

The public environment protocol is:

```python
class Environment(Protocol):
    async def setup(self, agents: Agents) -> None: ...
    async def run(self, task: Task, agents: Agents) -> None: ...
```

`Agents` is bound to the active per-seed trace, shared conversation recorder, event recorder, and current task step before it reaches the environment. A dialogue environment can therefore remain small. ADR-0003 defines the surrounding run as the collection-level invocation over the configured seed source.

```python
class DialogueEnv:
    async def run(self, task, agents):
        async with (
            agents.user.interaction(task) as user,
            agents.assistant.interaction(task) as assistant,
        ):
            request = await user.turn()

            while not request.terminated:
                response = await assistant.turn(request.last_reply)
                if response.terminated:
                    break

                request = await user.turn(response.last_reply)
```

The configured initiator determines which interaction produces the first message. After that, the built-in dialogue environment alternates `user` and `assistant`. A custom environment may express a different protocol directly in Python without a generic turn-order or routing abstraction.

The public API no longer exposes `current_agent`, `observe()`, or `step()`. A low-level AEC-like reducer may exist as an implementation detail or a future compatibility adapter, but it is not a second authoring model.

### An interaction turn is the acceptance boundary

`Interaction.turn()` is the deep operation that:

1. Constructs the agent's observation from its base instruction, current task-step instruction, full accepted conversation, and its private tool exchanges.
2. Invokes the agent and executes any private tool loop needed to obtain an outbound draft.
3. Runs the configured reviewer and asks the agent to revise rejected drafts up to the configured limit.
4. Commits the accepted tool calls, tool results, and outbound message to the shared conversation before returning.
5. Records model calls, rejected drafts, critiques, revisions, and failures in the separate event stream.
6. Returns the accepted `last_reply`, termination state, and review-exhaustion state to the environment.

An incoming `last_reply` is a reference to a message that the producing interaction already persisted. Passing it to the next interaction projects it into that agent's model history; it does not append a duplicate to the canonical conversation.

Tool calls and results remain private to the invoking agent when observations are projected. They are held with the pending turn until its outbound message is accepted, then committed together. If the turn fails before acceptance, they remain execution events rather than accepted conversation messages.

Task-step behavior is unchanged: accepted history survives every task step, an agent's base instruction remains active, and only the current step's instruction and appended rubric criteria are active. The runner invokes the final trace verifier only after `Environment.run()` finishes or truncates and the trace has been recorded.

### Dialogue roles are generic

The built-in two-party environment uses agent identifiers `user` and `assistant`. `user` denotes the simulated counterparty and `assistant` denotes the responding agent; neither name imposes a particular domain. A medical task may instruct them to behave as a patient and clinician, while another task may make them a customer and support agent, learner and tutor, or attacker and defender.

The task must still declare exactly one `target = true`; the role name does not determine which agent is the target. For the initial user-simulation workflow, the assistant is the target and the user is the simulator.

## Considered Options

- **Keep the public AEC protocol from ADR-0001.** Rejected because it exposes state-machine mechanics that every ordinary two-party environment must reconstruct. It is useful for Gym interoperability but not necessary for the framework's primary authoring workflow.
- **Expose both AEC and `Environment.run()` as equal public APIs.** Rejected because two lifecycle contracts would complicate persistence, review, termination, and custom-environment behavior. One deep interface is easier to learn and harder to misuse.
- **Give every domain first-class participant names.** Rejected because names such as patient and clinician leak the first consumer into the reusable framework. Those identities are instruction data, not execution primitives.

## Consequences

- Environment authors express interaction protocols with short, explicit Python loops similar to Prime Intellect's `UserSimEnv`.
- Model invocation, tools, review, and persistence remain consistent because environments can only access them through `Interaction.turn()`.
- Each accepted turn is durable before the next agent can consume it, while rejected drafts never enter model-visible history.
- The framework deliberately gives up Gym-style policy/environment separation at its primary extension point in exchange for a smaller and more natural multi-agent authoring surface.
- Existing references to patient and clinician in examples should be rewritten as user and assistant, with domain identities supplied through instructions.

## References

- [Prime Intellect `UserSimEnv`](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/envs/user_sim/env.py#L51-L99)
- [ADR-0001](./0001-data-generation-first-agent-trace-architecture.md)
- [ADR-0003](./0003-compile-one-run-plan-per-seed.md)
- [ADR-0004](./0004-review-model-messages-before-effects-and-export-complete-traces.md)
