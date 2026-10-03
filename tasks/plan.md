# Domain protocols and simpler generation modules

Date: 2026-10-03
Status: complete

The user requested a correctness review, a checkpoint commit, then deeper Python
modules with reusable protocols and less Environment machinery. The seven-module
checkpoint and its review fixes were committed as `6de2613`; the subsequent pass
is recorded in the [implementation report](../.scratch/deep-modules/implementation.md)
and [resolved work map](../.scratch/deep-modules/map.md).

```text
application: prepare Tasks/evaluators; own clients/resources around the batch
  -> Task(agents, input, segments, verifier): creates Episode and UUID immediately
  -> Runner(tasks, output_dir, client, environment=domain_instance): opens that Episode
     -> begin recording; apply Task deadline
     -> Environment.run(task, client): domain work; default UserSimEnv schedules segments
        -> Agent.generate / supplied Generator -> Evaluator review/revision
        -> durable acceptance -> approved Agent Tools
     -> record outcome; seal generation once; optional final Evaluator
  -> collect Task.episode; inspect/export or append independent verification
```

[ADR-0026](../docs/adr/0026-use-domain-protocols-and-runner-owned-task-lifecycle.md)
amends constructor-bound Environment and thin Runner ownership. Environment,
Generator and Evaluator each have one structural operation. Task/Episode remain
concrete data owners; approval/effects remain in Agent. No generic resource manager,
registry or alternate runtime owner is introduced. Application contexts own external
resources; SDK clients remain borrowed. [Migration guidance](../docs/migration-seven-modules.md)
describes the deliberate Python API changes; historical JSON remains readable.

Environment shrank from 196 to 45 lines. Environment + Runner + Task shrank from
334 to 257 lines. Total source is 4,271 lines (22 fewer than the checkpoint) across
17 files, with seven root exports, three protocols and nine fewer private definitions.
Every shipped function remains below 20 physical lines, including signatures/blanks
and excluding decorators. Exact per-file/owner counts are in the report.

All 222 offline tests, Ruff, strict mypy, function bounds, locked dependency checks,
wheel/sdist/package verification, seven examples and the mixed accepted/failed
CLI/export/reverification/TUI workflow pass. No live inference was required.

The [original implementation report](../.scratch/library-design-audit/implementation.md)
and [earlier work index](../.scratch/lean-core-refactor/map.md) retain their historical
checkpoint measurements; the current report supersedes their execution API guidance.
