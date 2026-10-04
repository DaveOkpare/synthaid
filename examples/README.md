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

The older `function-tool`, `multi-tool`, `stepped-dialogue`, `custom-components`,
`release-workflow` and `doubleword-medagent` examples use execution features removed
from UserSimEnv. Their declarations remain available for reference; running them
requires a custom Environment. UserSimEnv rejects Tool calls, segments and Task
deadlines explicitly.
