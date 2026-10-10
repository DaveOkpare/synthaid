Create a class called Agent, In this class we should have the following attributes and method:

> anything ~~struck through~~ is deprecated, the line under it says what replaced it.

1. Agent
  1. Model
    - this is a Model object (see Model below), not just a model name string.
  2. Instructions
  3. Output Type (default: str, supports Pydantic BaseModel)
  4. Tools
  5. ~~Eval (dtype: Eval, optional)~~
    - deprecated: evaluator: Callable[[Message], EvalResult] | None (see Agent in the changes below).
  6. run() -> This would use the ~~OpenAI Responses API~~
    - deprecated: run() uses the Chat Completions API through the openai SDK (no LiteLLM), the one endpoint for everything. not just openai, don't add things that only work with openai. structured output for the judge, reasoning for everything else.
      - if the agent has an eval, run() does the reflection loop (see 7). no eval means no reflection, all outputs are accepted.
      - ~~self._generate() makes one model call with openai's client.chat.completions.~~
      - deprecated: Model.generate() makes the one model call (see Model in the changes below).
  7. ~~run_with_eval() -> This is a reflection step where the output of the model is evaluated and critic is returned to the model. In this method, self.run() will be called then evaluated in a loop. The feedback from the eval is sent back to the model~~ `self.run()` ~~to refine its output. This would run in max_iterations loop. You can suggest a better Pythonic name for the function or this could be collapsed into run() itself.~~ See picture
    ![](https://www.philschmid.de/static/blog/agentic-pattern/reflection.png)
    - deprecated: run_with_eval() is collapsed into run(). the reflection loop works like this:
    - eval only sees the latest draft and checks it against its rubric. it gives back an EvalResult (see Eval below). stop early when it passes. if it never passes, return the last draft.
    - every eval run counts as one iteration. when a draft is accepted the count resets.
    - tool call messages get critiqued too.
    - the draft goes back as an assistant message and the feedback as a user message, so it shows up properly in the logs.
  8. max_iterations: total number of reflection iterations.
  9. logs (property/attribute): This would return all of the iterations made by the agent. This could be as a form of ChatML format too or a different format. But we need this in order to inspect runs and see if they worked properly.
    - each agent keeps its own logs, so Task.agents assistant and user each have theirs.

the reflection loop from 7:

```python
def run(self, messages):
    if self.eval is None:
        return self._generate(messages)
    for _ in range(self.max_iterations):        # each eval run = one iteration
        draft = self._generate(messages)
        result = self.eval(draft)                # judge sees the draft only
        if result.passed:
            break
        messages = [*messages, Message("assistant", draft), Message("user", result.feedback)]
    return draft                                 # last draft if it never passed
```

1. Environment
  1. run(self, task: Task) -> None

I have written a dummy function we can use. This function is poorly written. It is not clean and doesn’t properly state which agent is in use at the moment. histories[i] and histories[1-i]  can get quite confusing.

```python
def run_sim(agents, initial_prompt, max_iterations):
    if not (1 <= len(agents) <= 2):
        raise ValueError("`agents` must contain 1 or 2 callable functions.")

    text = initial_prompt.get("content", str(initial_prompt)) if isinstance(initial_prompt, dict) else str(initial_prompt)
    is_pair = len(agents) == 2

    # Setup local histories and external yield roles
    histories = [[{"role": "user", "content": text}], []] if is_pair else [[{"role": "user", "content": text}]]
    roles = ["user", "assistant"] if is_pair else ["assistant"]

    for _ in range(max_iterations):
        for i, agent in enumerate(agents):
            raw = agent(histories[i])
            out_text = raw.get("content", str(raw)) if isinstance(raw, dict) else str(raw)

            # Record assistant turn for self, user turn for opponent (if 2 agents)
            histories[i].append({"role": "assistant", "content": out_text})
            if is_pair:
                histories[1 - i].append({"role": "user", "content": out_text})

            yield {"role": roles[i], "content": out_text}
```

This function is yielding its result. We can use a loop or list of yielded history and assign it to Task.chat_history.

- split it out: Environment.run() calls _run_sim() once per step. task.chat_history is all the yields from the simulator, as Message objects (see Message below).
- in the dummy function, max_iterations is the number of turns. that's now the step's max_turns, not Agent.max_iterations.
- the step instruction goes to the user simulator only. the user sim's own view is thrown away, only messages the agents produce go into the history.
- the user sim always starts the step.
- one turn is one user and assistant exchange, so a step with max_turns=3 adds 3 user messages and 3 assistant replies.
- the user message prepared for the user sim says which turn it is out of max_turns, so it knows when to bring that part of the convo to a close.
- there's no system instruction on the task. each agent's system prompt is its own instructions, set when the agent is built.
- single agent: the instruction is the user message, agent output is the assistant message.
- ~~structured outputs get turned into JSON when passed on or stored.~~
- deprecated: structured outputs get turned into JSON when passed on (Message.text). the history keeps the Pydantic instance.

1. Task
  1. ~~instruction or list[instructions]. When a list of instructions is provided, the simulation loops through the list of instructions and each prompt is passed to the simulator as the initial prompt.~~
    - deprecated: steps: list[Step] (see Step below). think of them as different parts of the convo where we want the interaction to take a different turn. the simulation loops through the steps.
  2. chat_history (none/empty by default). This the the chat history and it is passed to every simulation, so ~~instructions[1:]~~ steps[1:] run_sims() are not cold started but build upon the chat history
  3. ~~agents: list[Agent]~~
    - deprecated: agents is a single Agent, or a tuple or dict of role (str) -> agent (Agent) for two agents, so it's clear who is talking.
  4. ~~turns: number of turns (back forth convo) to be produced.~~
    - deprecated: replaced by max_turns on each step.
2. Step
  1. instruction
  2. max_turns
    - max_turns doesn't apply for a single agent.
3. Tool
  1. name
  2. description
  3. parameters: dict - [JSON schema](https://json-schema.org/) defining the function’s input arguments
  4. function: Callable
4. Eval
  1. ~~rubrics: list[Criterion]~~
    - deprecated: criteria: list[Criterion].
    - criteria go in as a list[Criterion], each one ~~Criterion(title, content, weight, score)~~ Criterion(title, content, weight). the schema sent to the model only contains the `title`, `content` and `met` for the criterions in the list, while an extra field `feedback` is added. the model returns the title and `met` (a boolean) for each one. the weight stays on our side for ~~aggregate()~~ passes().
      - deprecated: no separate score field, we only use weight. when a criterion is met it counts as its weight, when it's not met it counts as 0. a negative rubric (something that shouldn't be there) has a negative weight, so if it's present the negative weight gets aggregated, and if not, 0 gets aggregated. same for positive weights.
      - the judge also returns an overall feedback string, so the agent knows what to fix.
  2. `__call__`~~: Callable. This function uses the output type from the llm and aggregates the scores and introduces a property passed: bool to the output_type.~~
    - ~~deprecated: `__call__` runs the judge, passes its results through aggregate(), and returns EvalResult(feedback, *, score, passed, metadata). we don't add passed onto the output_type.~~
    - deprecated: LLMJudge.`__call__` runs the judge, passes its results through passes(), and returns EvalResult(feedback, *, passed, metadata). we don't add passed onto the output_type.
      - ~~aggregate() is a protocol to follow. it returns a bool, and that's what sets passed. could be a weighted total against a threshold or every criterion passing.~~
      - deprecated: passes(criteria, threshold) -> bool sets passed. the default is the weighted total against a threshold.
      - if the user passes criteria, they get sent to the model and come back with `met` in the EvalResult metadata.
  3. ~~eval_func judge: Agent | Callable. By default the evaluator is an llm judge agent, i'm thinking we should make it either an agent or a function (code evals). The aggregator(call dunder) (i think we can find better pythonic names for all of these methods) then passes the values to the eval result type.~~
    - ~~renamed eval_func to judge. everything returns EvalResult.~~
    - deprecated: there's no judge field. LLMJudge is an Agent subclass and is passed as Agent(..., evaluator=LLMJudge(...)). a code eval is any function that takes a draft and returns an EvalResult. everything returns EvalResult.
5. Model (goes into the agent)
  1. base_url
  2. api_key
  3. model_name
  4. temperature (default: 0.7)
    call Chat Completions with the openai SDK pointed at base_url, so it works with any server that speaks Chat Completions (vLLM, Ollama, Groq, OpenRouter, etc).
6. Message
  Message class to capture the various types of messages (including tool message), alongside the reasoning. these are what get yielded to the history. the chat history sent to agents excludes the reasoning.
  - message types: system, user, assistant, tool call and tool result.
  - shape: Message(role, content, reasoning=None), one class. it should also capture tool call messages (call id, tool name, arguments).
  - ~~tool calls and tool results go into the chat history.~~
  - deprecated: only the assistant's tool calls and tool results go into the chat history. the user sim's tool calls stay in its own logs.
  - the agent logs use Message too, so drafts and critiques are in the same format.
  - a helper function prepares the messages for either agent. it drops the reasoning, and removes the tool messages that agent didn't produce (the call and its result together). so the user sim doesn't see the assistant's tool calls, and vice versa.
    - it also swaps the roles for the user sim: the assistant's replies become user messages and the user sim's own messages become assistant messages. the assistant's view needs no swap.

### changes i made that differ from plan

things the code converged to while building Model, Message, Tool and Agent. where these disagree with the parts above, these win.

1. Model
  - Model.generate() makes the one model call, not Agent._generate(). it sends one request and never runs tools or retries (beyond the openai SDK's own retries).
    - structured output goes through client.chat.completions.parse(), everything else through client.chat.completions.create().
    - Model is frozen so one Model can be shared by many agents. the openai client is created on first use and then reused.
    - api_key is optional. None lets the openai SDK read OPENAI_API_KEY.
2. Message
  - roles are system, user, assistant and tool. there's no separate tool call role, tool calls live on the assistant message as tool_calls, the same way Chat Completions does it.
    - a tool call is ToolCall(id, name, arguments), arguments already decoded from JSON. a tool result is Message("tool", content, tool_call_id=call.id) so the two can be matched.
    - content is text, a Pydantic instance (structured output), or None when the model only asked for tools.
    - message.text is the content as text: structured output becomes JSON, None becomes "". use it whenever content is passed on or stored.
    - reasoning is read from the `reasoning_content` field when the server sends one.
3. Tool
  - calling a tool with a ToolCall runs the function with the arguments as keyword arguments and returns the tool result Message. a result that isn't a string is turned into JSON.
    - tool errors live in synthaid.exception. a tool the agent doesn't have raises UnknownToolError, a function that raises gets wrapped in ToolExecutionError (the original error is its **cause**). errors are raised, not sent back to the model.
4. Agent
  - eval is now `evaluator: Callable[[Message], EvalResult] | None`. any callable that takes a draft and returns an EvalResult works, so Eval just needs a **call**.
    - run(messages) takes one turn and returns the messages it added: every accepted draft with tool calls, then its tool results, then the final reply. rejected drafts and critiques only go to the logs.
    - run() adds the system message from instructions, so messages must not contain one.
    - critiques are only sent while retrying that draft. once a draft is accepted they're dropped and not carried into later requests.
    - when an accepted draft has tool calls, the tools run and the model is asked again. the turn ends with the first accepted draft without tool calls.
    - checked when the agent is built: tools can't be combined with structured output, tool names must be unique, max_iterations must be at least 1.
    - one Agent serves one role in one conversation. share the Model, not the Agent.
    - logs keep growing across runs and survive errors. every run starts with the system message and its input messages again.
5. Eval
  - EvalResult is frozen. feedback is positional, passed and metadata are keyword only. metadata defaults to an empty dict. there's no score field, it was dropped.
    - there's no Eval class. the llm judge is LLMJudge(model, criteria, instructions, *, passes, threshold), an Agent subclass, used as Agent(..., evaluator=LLMJudge(...)). a code eval is any function that takes a draft and returns an EvalResult.
    - LLMJudge is an Agent with output_type=Verdict, max_iterations=1, no tools and no evaluator of its own. instructions default to a strict judge prompt. its logs keep every draft it judged, so give each conversation its own judge.
    - rubrics is now criteria. Criterion(title, content, weight=1.0) is a frozen Pydantic model, and the judge fills in `met`. weight is left out of the schema sent to the model and `met` is required in the reply. there must be at least one criterion and titles must be unique.
    - the judge's output type is Verdict(criteria, feedback). it's checked against our criteria: each one must be answered exactly once, or a pydantic.ValidationError is raised. the result keeps our order and weights, with `met` from the reply.
    - aggregate() is now `passes(criteria, threshold) -> bool`. the default passes when the weights of the met criteria add up to at least threshold. threshold defaults to the sum of the positive weights, so by default a draft passes only when every positive criterion is met and no negative one is.
    - the judge gets one user message: the criteria, then the draft as text, then its tool calls as name(json arguments). it never sees the reasoning or the conversation the draft came from.
    - EvalResult.metadata["verdict"] holds the Verdict, so the answered criteria come back to the caller.
6. Task and Step
  - Task and Step are definitions only. Environment runs the exchange and appends to task.chat_history.
    - agents is now two named fields: Task(assistant, steps, user=None, chat_history=[]). user=None means a single agent. the same Agent can't be both user and assistant.
    - steps can't be empty, and chat_history can't contain a system message, since each agent adds its own.
    - Step(instruction, max_turns=1) is frozen. max_turns must be at least 1.
7. Environment
  - Environment.run(task) loops through the steps and appends every message _run_step() yields to task.chat_history, so the history keeps finished turns if an agent raises.
    - _run_step() loops through the turns and yields the accepted messages: the user message, then everything assistant.run() returned. it works on its own copy of the history.
    - the user sim's view is built from chat_history by _user_view(), not from its logs (logs repeat the system message and inputs every run). its tool calls stay in its logs, and its final reply is added as a user message, keeping its reasoning.
    - the turn note starts with "Simulator note:", gives the step instruction and "turn k of n", and on the last turn asks the sim to close that part. it's merged into the last user message of the view, or added as its own user message when the view doesn't end with one.



the reflection loop from 7, as the code does it:

```python
def run(self, messages):
    system = Message("system", self.instructions)
    output = []
    while True:
        rejected = []                                # critiques for this draft only
        for _ in range(self.max_iterations):         # each eval run = one iteration
            draft = self.model.generate([system, *messages, *output, *rejected])
            if self.evaluator is None:
                break
            result = self.evaluator(draft)           # judge sees the draft only
            if result.passed:
                break
            rejected += [draft, Message("user", result.feedback)]
        output.append(draft)                         # last draft if it never passed
        if not draft.tool_calls:
            return output
        output += [self.tools[call.name](call) for call in draft.tool_calls]
```

