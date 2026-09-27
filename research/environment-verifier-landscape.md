# Environment and verification landscape

Research date: 2026-09-23. Primary sources only. The `verifiers` source was inspected at commit [`0b46c8c`](https://github.com/PrimeIntellect-ai/verifiers/tree/0b46c8c22ebada6c45b34391be7d55d39f1a2006).

## Executive conclusion

The three projects use “environment” at different depths:

- **OpenEnv** is a typed Gym-style state machine. A caller resets an environment, repeatedly submits one action, receives one observation/reward/termination result, and owns model generation. It is not a multi-agent conversation orchestrator.
- **ORS** is a language-neutral wire protocol for stateful tool-call episodes. Every action is a tool call; the environment returns content blocks, one optional scalar reward, and `finished`. It intentionally knows nothing about chat messages or agents.
- **Prime Intellect Verifiers v1** is the closest match for the proposed framework. Its `Env.run(task, agents)` owns multi-agent control flow. Its user-simulator environment opens two agent interactions and explicitly relays replies between them.

For this data-generation library, copy Verifiers' high-level ownership boundary and OpenEnv's typed episode lifecycle, but do not copy their trace/reward models wholesale. Concretely:

1. Rename “where code runs” to **Runtime** (`local` in v1). Reserve **Environment** for the stateful world/control flow in which agents interact.
2. Make `Environment.run(context)` the deep public interface. The built-in two-party dialogue environment owns back-and-forth interaction; do not put a generic `turn_order` list or a `TurnPolicy` abstraction in task TOML.
3. Keep one canonical accepted-message history across every task step. Draft/review/rejected/internal events belong to a separate event stream and are not model-visible chat.
4. Make termination typed: `terminated` for a legitimate scenario ending, `truncated` for budgets/errors. Do not collapse both into `done`.
5. Define verification as named boolean criteria plus a distinct execution error. Persist every raw run; derive acceptance/export eligibility separately.

## What each system owns

| Concern | OpenEnv | Open Reward Standard | Verifiers v1 |
|---|---|---|---|
| Primary abstraction | Typed state machine | HTTP tool-call episode | Multi-agent episode program |
| Control loop | External caller does `reset`/`step` | External client calls tools until `finished` | `Env.run(task, agents)` programs the complete interaction |
| Action | Environment-specific typed `Action` | Always a named tool call with JSON input | An agent run or one `Interaction.turn(...)`; env code decides who runs next |
| Observation | Typed `Observation`; client exposes observation, reward, `done`, metadata | Text/image blocks in `ToolOutput` | `Segment` for a turn and one `Trace` per agent; an `Episode` groups traces |
| State | Environment instance, queryable through `state` | Server-side environment instance scoped to session | Runtime/trace state belongs to each agent rollout; env coordinates agents |
| Tools | Environment-specific actions; optional MCP boundary | Tools are the only agent/environment boundary | Tasks/toolsets and harnesses expose tools; env composes agents |
| Multi-party | Not first-class; one action stream | Deliberately agent/chat agnostic | First-class roles declared as agents; env explicitly coordinates them |
| Termination | One `done` boolean | `finished`, independent of success | Segment/trace stop conditions and episode success/errors |
| Verification | Server-side numeric rubrics/rewards | One optional scalar reward per tool result | Named metrics/rewards; deterministic task functions or LLM/agentic judges |

## 1. OpenEnv

### Lifecycle and ownership

The core [`Environment`](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_server/interfaces.py#L197-L286) requires `reset(...)`, `step(action, ...)`, and a `state` property. Its base types are Pydantic models: `Observation` carries `done`, `reward`, and metadata, while `State` carries episode identity and step count ([source](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_server/types.py#L44-L78)). The client normalizes these into a [`StepResult`](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/client_types.py#L8-L25).

This means the environment owns:

- action validation and state transition;
- the agent-visible observation;
- reward computation;
- episode termination;
- persistent episode state.

It does **not** own model invocation or a participant schedule. The rollout loop is external: inspect observation, generate an action, call `step`, repeat until done. The current source uses `done`; an official concepts snippet saying `terminated` is stale relative to the source.

The client/server split is worth reusing later. One asynchronous client maintains a persistent WebSocket session ([client](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_client.py#L217-L244)); the server creates an independent environment instance per WebSocket ([server/session setup](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_server/http_server.py#L332-L406)). The `/ws` loop dispatches `reset`, `step`, and `state` against that instance ([source](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_server/http_server.py#L1368-L1464)). By contrast, its plain HTTP reset/step endpoints construct fresh environments and are stateless debugging surfaces ([source](https://github.com/huggingface/OpenEnv/blob/main/src/openenv/core/env_server/http_server.py#L616-L674)).

### Multi-party interaction

Multi-party behavior is environment-specific, not part of the core protocol. OpenSpiel explicitly presents a single-agent interface: after the controlled agent acts, the environment automatically runs fixed-policy opponents until it is the controlled agent's turn again ([source](https://github.com/huggingface/OpenEnv/blob/main/envs/openspiel_env/server/openspiel_environment.py#L2-L10)). Participant fields such as current player and opponent action live in that environment's own models, not in `Environment`.

Therefore OpenEnv does not itself place two independent LLM agents into a conversation. Either an external rollout orchestrator invokes the models, or the environment internally simulates the other side. That distinction matters: our framework needs independent, traceable participants, so OpenEnv's one-action-stream core is insufficient by itself.

### Rewards/verifiers

Rewards live inside the environment and run during `step`. OpenEnv's rubric system treats a rubric as `forward(action, observation) -> float` and composes scalar rewards with `Sequential`, `Gate`, and `WeightedSum`; trajectory rubrics accumulate action/observation pairs until completion ([reward guide](https://github.com/huggingface/OpenEnv/blob/main/docs/source/guides/rewards.md), [rubric RFC](https://github.com/huggingface/OpenEnv/blob/main/rfcs/004-rubrics.md)). This is useful for RL credit assignment, but it couples verification to state transitions and reduces named outcomes to a scalar. A dataset generator should retain named criterion results before any aggregation.

## 2. Open Reward Standard (ORS)

ORS defines one session as one stateful episode. The sequence is: create a session, instantiate an environment with a task, fetch the prompt, call tools repeatedly, and clean up ([protocol lifecycle](https://openrewardstandard.io/specification/overview)). The server owns episode state and tool execution; the client owns the agent loop.

Its strongest design rule is also its limitation for this project: **all actions are tools**, and the protocol intentionally has no notion of chat messages or tokenized model output. This keeps the environment independent from any agent implementation ([ORS overview, “Actions are Tools”](https://openrewardstandard.io/)).

The result schema is deliberately small:

```text
ToolOutput {
  blocks: TextBlock[] | ImageBlock[]
  reward?: number
  finished: boolean
  metadata?: object
}
```

See the normative [data types](https://openrewardstandard.io/specification/data-types). `finished` means the episode is over whether it succeeded or failed; reward or output content carries that distinction. Server/tool failures are also kept separate from valid tool outputs ([protocol error handling](https://openrewardstandard.io/specification/overview)). That separation is worth copying for verifier failures.

ORS has no standard multi-criterion verifier result and no multi-party scheduling. Its scalar reward is suited to RL interoperability, not as the canonical verification artifact for generated datasets. ORS compatibility could later be an environment/tool adapter, not the framework's internal conversation or trace schema.

## Multi-agent Gym precedent: PettingZoo AEC

The closest established Gym-style interface for sequential multi-agent interaction is PettingZoo's Agent Environment Cycle (AEC). An AEC environment exposes the currently selected participant through `agent_selection`; the external runner obtains that participant's observation, asks its policy for one action, and submits that action to `env.step(action)`. The environment then updates its state and selects the next participant ([AEC usage](https://pettingzoo.farama.org/api/aec/#usage), [`AECEnv.step`](https://pettingzoo.farama.org/api/aec/#pettingzoo.utils.env.AECEnv.step)).

This changes the recommended public API for a Gym-compatible version of this project: keep model invocation in a runner and let the environment own state transitions, participant selection, phase advancement, termination, truncation, observations, and rewards. A convenience `run_episode(env, agents)` deep module can hide the loop for ordinary users. Having one `step()` call invoke both agents would make the environment convenient but would no longer follow the standard Gym/AEC separation between policy and environment.

## 3. Prime Intellect Verifiers v1

### Environment as multi-agent control flow

Verifiers' current `Env` is the best precedent for the requested design. The interface is explicitly `Env.run(task, agents) -> None`, and the documentation says the env defines control flow between agents ([docs](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/docs/v1/env.md#L1-L21), [source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/env.py#L76-L184)). Each named role is an `Agent`; every completed run contributes a role-stamped trace to one `Episode` ([episode schema](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/episode.py#L87-L151)).

The concrete [`UserSimEnv`](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/envs/user_sim/env.py#L51-L99) demonstrates the desired back-and-forth interaction:

1. Open one interaction for the simulated user and one for the assistant.
2. Ask the user model for an opening request.
3. Pass that reply to the assistant.
4. Pass the assistant reply back to the user.
5. Stop on a marker or an agent limit.

There is no generic turn-policy object. The environment implementation owns the protocol in ordinary Python. The agent's [`Interaction.turn`](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/agent.py#L171-L259) is a strict request/response segment and returns messages, the root reply, and whether the interaction terminated.

One aspect should **not** be copied: Verifiers records separate agent traces and relays text between them. Our target artifact is a multi-party conversation, so it should have one canonical accepted-message stream with actor IDs. Per-agent model calls and private reviewer events can reference that stream without becoming duplicate conversations.

### Verification and reward schemas

Verifiers separates per-trace scoring from cross-agent finalization. A `Task` can define deterministic metrics/rewards or plugged judges; each may return a scalar or a mapping of names to floats ([task scoring](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/task.py#L203-L274)). A trace stores named weighted rewards and named unweighted metrics ([trace schema](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/trace.py#L399-L448)).

The rubric judge supplies two particularly reusable rules:

- Criteria have stable unique names and default binary choices `no`/`yes` ([criterion schema](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/judges/rubric.py#L60-L110)).
- The judge output is validated as a complete, duplicate-free set with allowed verdict values; malformed output raises instead of being scored as model failure ([validation](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/judges/rubric.py#L146-L183)).

Its agentic judge also separates judge execution from applying results to the solver: it records a per-criterion metric, then optionally aggregates weighted scores into a reward ([source](https://github.com/PrimeIntellect-ai/verifiers/blob/0b46c8c22ebada6c45b34391be7d55d39f1a2006/verifiers/v1/envs/agentic_judge/env.py#L318-L336)). That separation is more important than its numeric weighting.

## Recommended v1 interfaces

### Separate Environment from Runtime

```python
class Runtime(Protocol):
    """Where agents and tools execute: local in v1; Docker/remote later."""

class Environment(Protocol):
    async def run(self, context: InteractionContext) -> EnvironmentOutcome:
        """Own the complete single- or multi-agent episode control flow."""
```

`Environment.run` should be the public deep module, following Verifiers. The runner supplies participants, task steps, seed bindings, agents, tools, recorder, and runtime through `InteractionContext`; environment implementations decide when to invoke each participant and when to stop. The built-in `dialogue` environment provides strict two-party alternation. Task TOML chooses the environment but does not expose a generic `turn_order` or routing graph.

Underneath, a reducer can use OpenEnv-like typed transitions without making them a user-facing workflow API:

```python
class MessageAction(BaseModel):
    actor_id: str
    message: Message

class EnvironmentObservation(BaseModel):
    phase_id: str
    accepted_messages: list[Message]
    terminated: bool = False
    truncated: bool = False
    stop_reason: str | None = None
```

The environment validates the actor/action, accepts or rejects it, appends only accepted messages, advances its internal actor/phase state, and decides termination. `terminated` means a valid endpoint; `truncated` means a turn cap, timeout, provider failure, or other incomplete endpoint.

### History and task steps

Maintain two ordered structures:

```text
conversation: accepted participant/tool messages only
events: drafts, reviewer critiques, revisions, rejected actions, model calls,
        verifier executions, errors, and lifecycle transitions
```

The accepted conversation is retained across every task step and is the only chat history supplied to models. At a step boundary, an agent receives:

```text
base agent instruction + current step instruction + full accepted conversation
```

The previous step instruction expires; the conversation does not. Event records can point to the accepted message they produced, but they must not be inserted into participant-visible history.

### Tools

Keep lifecycle control (`run`, internal transition/state) separate from agent-facing tools. ORS's Cartesian boundary is valuable: a tool must not need to know which model framework called it. An MCP/ORS adapter can be added later, but the v1 tool protocol only needs typed name/schema/call/result and an actor-aware call context. Tool results become accepted conversation messages only when the environment accepts them; execution metadata stays in events.

### Minimal verifier protocol

```python
class Criterion(BaseModel):
    id: str
    description: str

class VerificationResult(BaseModel):
    criteria: dict[str, bool]

class Verifier(Protocol):
    async def verify(self, context: VerificationContext) -> VerificationResult: ...
```

Rules:

- Criterion IDs are declared once and unique.
- A result must contain every declared ID exactly once and no unknown IDs.
- Deterministic code verifiers and LLM judges implement the same protocol.
- An exception/timeout/malformed judge response produces `VerifierError`, not `{criterion: false}`.
- The canonical result remains boolean. Any aggregate reward or acceptance flag is derived data.

This also resolves the earlier “selection policy” ambiguity. In v1, do not make the verifier decide retention. Persist every raw run and its verification result. Define `accepted = all(result.criteria[id] for id in required_criteria)` as a derived field, and let export default to accepted traces while supporting `--include-rejected`. A false criterion is useful negative data; a verifier error means the trace was not successfully judged.

## What not to copy

- Do not copy OpenEnv's single `done` bit; dataset provenance needs legitimate termination versus truncation.
- Do not copy OpenEnv's scalar rubric result as the canonical verifier artifact; retain named booleans.
- Do not copy ORS's assumption that every meaningful action is a tool call; participant messages are first-class actions here.
- Do not put agent/chat semantics into an ORS-compatible tool server; keep that adapter at the boundary.
- Do not copy Verifiers' separate relayed conversations as the canonical multi-party trace; use one accepted-message stream.
- Do not expose arbitrary routing, parallelism, event-driven wakeups, or background-message machinery in v1. A custom environment remains the extension point if a later workload genuinely needs a different interaction protocol.
