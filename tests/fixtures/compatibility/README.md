# Pre-refactor artifact baseline

`v0.1.0-reviewed-trace/` contains the **unaltered** `trace.json` and final
Verification sidecar captured on 2026-10-01 from agentinstruct 0.1.0 at commit
`4c5044264d09706f7c4905295191f52eae23fe8b`, before the lean-core refactor.

It was generated offline through the former synchronous API and the historical
synthetic components in `tests.component_fixtures`. Those runtime imports and
Runner factory/storage arguments have since been removed; the captured files
remain independent of their original components.

Read the baseline with the current API:

```python
from agentinstruct import Episode

trace = Episode.load("tests/fixtures/compatibility/v0.1.0-reviewed-trace")
print(trace.status, len(trace.messages))  # accepted, 5
```

The disposable Task Package and Run were removed after capture. The two JSON
files total 18,428 bytes; there are no credentials, machine paths, model calls,
source files, or duplicate conversation/event/plan files. The snapshot retains
the seed, rendered Run Plan, component digests, five accepted Message Commits,
private target Tool calls/results, and a rejected proposal/revision in Events.
The sidecar supplies the final accepted Verification; the sealed generation
snapshot correctly remains `unverified`.

Read tests must consume these fixed artifacts without rebuilding them or
importing their original components. Future writers cannot prove historical
compatibility by generating a fresh fixture; add a separately versioned capture
when a new persisted-format baseline is needed.
