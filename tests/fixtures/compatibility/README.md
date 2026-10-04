# Pre-refactor artifact baseline

`v0.1.0-reviewed-trace/` contains the **unaltered** `trace.json` and final
Verification sidecar captured on 2026-10-01 from agentinstruct 0.1.0 at commit
`4c5044264d09706f7c4905295191f52eae23fe8b`, before the lean-core refactor.

It was generated offline through the former synchronous API and the historical
synthetic components in `tests.component_fixtures`. Those runtime imports and
Runner factory/storage arguments have since been removed; the captured files
remain independent of their original components.

The current Episode no longer loads this historical format. Inspect the captured
JSON directly when researching the earlier design:

```python
import json
from pathlib import Path

source = Path("tests/fixtures/compatibility/v0.1.0-reviewed-trace/trace.json")
trace = json.loads(source.read_text())
print(trace["status"], len(trace["conversation"]))  # unverified, 5
```

The disposable Task Package and Run were removed after capture. The two JSON
files total 18,428 bytes; there are no credentials, machine paths, model calls,
source files, or duplicate conversation/event/plan files. The snapshot retains
the seed, rendered Run Plan, component digests, five accepted Message Commits,
private target Tool calls/results, and a rejected proposal/revision in Events.
The sidecar supplies the final accepted Verification; the sealed generation
snapshot correctly remains `unverified`.

The files remain unchanged as historical evidence. The current reader test checks
that this format is rejected explicitly, without importing its original components.
