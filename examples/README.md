# Examples

Start with `direct-dialogue/run.py`: two Agents speak, review their responses and
optionally verify the recorded Episode. It runs offline:

```sh
uv run python examples/direct-dialogue/run.py --output /tmp/agentinstruct-dialogue
```

The task-file examples `scripted-single`, `scripted-dialogue`, `reviewed-dialogue`,
`verified-single`, `seed-collection` and `seed-sources` use model Agents with the
default UserSimEnv. The folders retain their historical names; scripted Agents
are removed. Configure the model name and credentials before running them.

`single-agent` and `responses` use configured model clients. All model clients
must connect to a server supporting `/v1/responses`.
`structured-quality/run.py` demonstrates model generation and judging offline
through the SDK with an HTTP fixture.

The older `function-tool`, `multi-tool`, `custom-components` and
`doubleword-medagent` examples need a custom Environment to execute Tools.
`stepped-dialogue` and `release-workflow` remain historical references; their step
declarations are no longer supported by the task-file loader.

For dialogue, put the user before the assistant in the Agent dictionary or TOML
tables. This order determines who starts. `max_turns` limits the total messages.
