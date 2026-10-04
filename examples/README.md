# Examples

Start with `direct-dialogue/run.py`: two Agents speak, review their responses and
optionally verify the recorded Episode. It runs offline:

```sh
uv run python examples/direct-dialogue/run.py --output /tmp/agentinstruct-dialogue
```

The task-file examples `scripted-single`, `scripted-dialogue`, `reviewed-dialogue`,
`verified-single`, `seed-collection` and `seed-sources` also run offline with the
default UserSimEnv.

`single-agent`, `chat-completions` and `structured-quality` use model clients.

The older `function-tool`, `multi-tool`, `custom-components` and
`doubleword-medagent` examples need a custom Environment to execute Tools.
`stepped-dialogue` and `release-workflow` remain historical references; their step
declarations are no longer supported by the task-file loader.

For dialogue, put the user before the assistant in the Agent dictionary or TOML
tables. This order determines who starts. `max_turns` limits the total messages.
