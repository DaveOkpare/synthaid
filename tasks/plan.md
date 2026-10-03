# Restore Runner to the specification's Task loop

Date: 2026-10-03
Status: complete

The user rejected the Runner-owned lifecycle in commit 5367d23 and reaffirmed
the [original specification](../.scratch/library-design-audit/spec.md). Restore
Runner to opening each existing Episode, invoking Environment and collecting it.
The [correction report](../.scratch/deep-modules/runner-correction.md) and
[ticket 05](../.scratch/deep-modules/issues/05-restore-runner-loop.md) record this work.

```text
application: prepare Tasks/evaluators; own clients/resources around the batch
  -> Task: owns Episode and UUID immediately
  -> Runner: for each Task, open Episode at output_dir / episode.id
     -> Environment.run(task, client): own execution/deadline/finalization
        -> default UserSimEnv: begin; execute segments via Agent; seal; final evaluator
           -> Agent: generate; review/revise; durable acceptance; approved Tools
     -> Runner: collect that same Episode
  -> application: inspect/export or append independent verification
```

[ADR-0027](../docs/adr/0027-restore-runner-to-the-task-loop.md) restores the intended
Runner/Environment responsibilities. Structural protocols, application-owned
resources and ready evaluators remain. Custom Environments own their execution
policy and errors propagate through Runner unchanged. No lifecycle wrapper,
registry or runtime owner is added.

Runner is 31 lines, down from 104, and contains only __init__ and run. Environment
is 116 lines including the required execution safeguards; combined source drops
from 149 to 147 lines. Total shipped source is 4,269 lines across 17 files. All
shipped functions stay below 20 physical lines. Exact counts are in the report.

225 offline tests, Ruff, strict mypy and the package/workflow release checks pass.
Earlier reports preserve measurements at 6de2613 and 5367d23; the correction report
and migration guide describe current execution ownership.
