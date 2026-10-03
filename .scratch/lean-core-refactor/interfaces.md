# Current interface: actual owners and ordinary records

This describes [ADR-0012](../../docs/adr/0012-keep-runner-as-an-environment-task-loop.md):
Runner iterates prepared tasks and calls its Environment. Environment creates,
records, and finally verifies one whole Episode per task.

The user removed all Plans, ToolContext, StepProgress, AgentTool and built-in
control Tools. [ADR-0011](../../docs/adr/0011-remove-plans-and-use-ordinary-task-records.md)
supersedes the intermediate interface. No old factory arguments remain.

```python
provider = ChatCompletionsProvider("http://127.0.0.1:8000/v1")
user = Agent("Act as a customer.", "model", id="user", target=False, provider=provider)
assistant = Agent(
    "Handle returns.",
    "model",
    provider=provider,
    tools={"policy": FunctionTool("policy", read_policy)},
    reviewer=reviewer,
    rubric=rubric,
)
environment = DialogueEnvironment(
    user, assistant, max_rounds=3, verifier=final_verifier, output_dir="runs"
)
async with environment:
    episodes = await Runner(environment, [{"item": "lamp"}]).run()
for episode in episodes:
    print(episode.status, episode.path)
```

```text
application load/parse/prepare -> records -> Runner: iterate and call
  -> Environment.run(record): start a fresh Episode
     -> conversation(Episode): schedule actual Agent.turn(Episode)
     -> generate -> own Review/revise -> durable commit -> private Tools
     -> seal whole Episode -> final Verification
  -> caller: inspect/export
```

Customize Agent.generate(observation), Environment.conversation(episode), Tool.call(args),
Reviewer.review(request), or Verifier.verify(trace). Tools capture application
data through ordinary closures. `async with environment` keeps resources alive
across its tasks, then closes its actual Agent/Reviewer/Verifier resources.
Runner returns `list[Episode]` and owns no persistence, cleanup, or final grading.
Episodes stay recorded at `output_dir/<episode-id>`; `environment.episode` retains
the latest one, including failed or cancelled attempts.

TaskPackage.load/compile/validate is optional authoring. compile returns frozen
JSON metadata. `await package.create_environment(record)` binds actual owners;
`generate(package, output_dir="runs")` also writes Run manifests/indexes and
returns a `RunResult`. It takes no `runner=` override. Declared phases expand into
separate records; application Python chooses subsequent tasks. Runner takes only
an Environment and tasks; its `run()` takes no arguments.

Executable domain example: [retail dialogue](../../examples/direct-dialogue/run.py).
Saved Trace fields remain readable without original components or Plan models.
