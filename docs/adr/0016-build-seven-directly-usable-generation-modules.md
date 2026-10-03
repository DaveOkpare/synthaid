---
status: accepted
date: 2026-10-03
implementation: implemented; refined by ADR-0025
amends:
  - ADR-0006
  - ADR-0009
  - ADR-0011
  - ADR-0012
  - ADR-0014
  - ADR-0015
---

# Build seven directly usable generation modules

[ADR-0017](0017-use-agent-reviewers-task-verifiers-and-independent-episodes.md)
refines configuration: optional reviewer on each Agent, optional verifier on Task,
and one independent output Episode per Environment run. The seven modules remain.

[ADR-0019](0019-task-owned-episodes-span-segments.md) moves Episode ownership to
Task, retaining history across its ordered segments without adding a core module.

The [refactor spec](../../.scratch/library-design-audit/spec.md#reusable-judge-constructor)
clarifies the existing shared-Judge decision: one constructor/evaluate interface,
with reusable instances and invocation state kept outside Judge. Its client
example records application ownership across the batch; SDK adoption remains pending.

[ADR-0022](0022-construct-agent-definitions-and-revise-from-review.md) specifies
that Agent uses the rejected draft and reviewer guidance to generate a replacement.
[ADR-0023](0023-use-agent-directly-and-keep-execution-state-local.md) uses Agent's
constructor directly, superseding the separate definition record. The seven-module
layout remains unchanged.

## Decision

The generation library consists of Task, Runner, Environment, Agent, Episode,
Tools and Judge. Users import these directly to generate synthetic data for their
use case. The earlier plan retained too many supporting files and abstractions;
the accepted target requires deleting and simplifying that machinery.

```text
task.py          ordinary execution definitions/settings
runner.py        per-Task setup/run loop
environment.py   setup(task) and run(), participant setup and conversation
agent.py         generation, review/revision, acceptance and private Tool use
episode.py       accepted history, evidence, persistence and export
tools.py         callable Tool and local input/output validation
judge.py         message/episode judgment, Rubrics and scoring
```

__init__.py exposes seven primary imports. Small supporting data values stay in
the module that owns them. Taskset remains list[Task]. Public Environment is a
usable built-in implementation; structural custom Environments satisfy the same
two methods without requiring a public Protocol-only class or subclass hierarchy.

Judge is the canonical public name. Reviewer and Verifier are the message and
episode roles of judgment, not parallel request/call/result hierarchies. Agent
enforces revisions and acceptance. Environment's final judge consumes the sealed
Episode's accepted history; shared mechanics do not merge the two decisions.

Agent.turn calls generate for proposals and owns review/revision, accepted
recording and approved Tool execution. generate is the customization seam rather
than another full execution operation. A model call can perform I/O; the proposed
message remains unaccepted until turn applies the acceptance mechanism.

Episode exposes accepted Conversation through a read-only messages attribute.
Consumers do not call export merely to read their result. Serialization/format
conversion is optional and retains explicit target/visibility selection; drafts
and review Events stay separate from accepted messages.

## Deletion and simplification

- Replace execution.py with Agent and Environment modules.
- Replace store.py/traces.py/export.py with one Episode implementation; remove
  redundant live/reference/snapshot wrappers and the core Run-store owner.
- Replace review.py/verification.py/quality.py/quality_provider.py with Judge.
- Retire Provider request/response/control models and duplicated wire models.
  Agent and Judge receive an injected model client or ordinary async callable.
  SDK types remain implementation details rather than public generation concepts.
- Remove standalone structured/data/failures/paths subsystems. Retain required
  validation, safe recording and cleanup operations with their real owners.
- Replace TaskPackage/Seed/component-registry machinery with a small optional
  Task-file loader. CLI, inspection, TUI and vLLM startup remain optional consumers.
  Their existence does not expand the generation interface.

Do not concatenate removed files into oversized new ones, or mirror them under
private namespaces. Simplify representations, branches, construction and ownership
as the files are removed. Few meaningful methods per primary class and fewer than
20 inclusive physical lines per function/method are explicit requirements. Avoid
forwarding helpers, compressed formatting and extra records to satisfy the count.

The [refactor plan](../../.scratch/library-design-audit/spec.md) specifies current
file dispositions and observable proof for each slice. A mature client such as
the [official OpenAI Python client](https://github.com/openai/openai-python) is a
candidate for removing handwritten transport; adoption/version selection remain
pending parity checks. No dependency has been added. Local schema validation,
accepted reasoning, call evidence and the current no-retry behavior still apply.

## Consequences

This intentionally replaces ADR-0006's framework Provider layer and ADR-0009's
current canonical imports. It changes Python imports and custom extension shapes,
with migration notes and updated examples, without compatibility aliases. Keep
saved Trace JSON readable and active task-file syntax supported by the optional
loader. Removal is broader than a behavior-neutral file relocation.

ADR-0014's Task records and ADR-0015's setup/run sequence remain. Preserve
review-before-effects, durable intent, private history, final accepted-history
judgment, immutable generation, append-only verification and explicit resource
ownership. Fewer modules must not erase these behavioral guarantees.

Implementation is unstarted. Current code and README remain the implementation
checkpoint; the revised specification describes the target. Report genuine
deletion separately from relocation, and core file counts separately from optional
files and packaging markers.

## Implementation checkpoint — 2026-10-03

Implemented through the [seven-module refactor](../../.scratch/library-design-audit/implementation.md).
[ADR-0025](0025-implement-constructor-bound-environments-and-borrowed-sdk-clients.md)
resolves the constructor/run interface, one Task per execution, and borrowed SDK
client adoption. Earlier lifecycle examples above remain historical.
