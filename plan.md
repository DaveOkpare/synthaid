Create a class called Agent, In this class we should have the following attributes and method:

1. Agent
  1. Model
  2. Instructions
  3. Output Type (default: str, supports Pydantic BaseModel)
  4. Tools
  5. Eval (dtype: Eval, optional)
  6. run() -> This would use the OpenAI Responses API
  7. run_with_eval() -> This is a reflection step where the output of the model is evaluated and critic is returned to the model. In this method, self.run() will be called then evaluated in a loop. The feedback from the eval is sent back to the model `self.run()` to refine its output. This would run in max_iterations loop. You can suggest a better Pythonic name for the function or this could be collapsed into run() itself. See picture  
     - decided: collapse it into run(). if the agent has an eval, run() does the reflection loop. no eval means no reflection, all outputs are accepted.
     - eval only sees the latest draft and checks it against its rubric. it gives back feedback + passed (see Eval below). stop early when it passes. if it never passes, return the last draft.
     - every eval run counts as one iteration. when a draft is accepted the count resets.
     - tool call messages get critiqued too.
  ![](https://www.philschmid.de/static/blog/agentic-pattern/reflection.png)8. max_iterations: total number of reflection iterations.  
  9. logs (property/attribute): This would return all of the iterations made by the agent. This could be as a form of ChatML format too or a different format. But we need this in order to inspect runs and see if they worked properly.   
     - each agent keeps its own logs, so Task.agents assistant and user each have theirs.

2. Environment
  1. run(self, task: Task) -> NoneI have written a dummy function we can use. This function is poorly written. It is not clean and doesn’t properly state which agent is in use at the moment. histories[i] and histories[1-i]  can get quite confusing.

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
  - split it out: Environment.run() calls _run_sim(). task.chat_history is all the yields from the simulator.
  - for two agents, take a tuple or dict of role (str) -> agent (Agent), so it's clear who is talking.
  - the segment instruction goes to the user simulator only. the user sim's own view is thrown away, only messages the agents produce go into the history.
  - single agent: the instruction is the user message, agent output is the assistant message.
  - structured outputs get turned into JSON when passed on or stored.
  - not just openai, don't add things that only work with openai.
3. Task  
    1. instruction or list[instructions]. When a list of instructions is provided, the simulation loops through the list of instructions and each prompt is passed to the simulator as the initial prompt.   
    2. chat_history (none/empty by default). This the the chat history and it is passed to every simulation, so instructions[1:] run_sims() are not cold started but build upon the chat history  
    3. agents: list[Agent]

     4. turns: number of turns (back forth convo) to be produced.  
     - decided: split the task into segments. think of them as different parts of the convo where we want the interaction to take a different turn. each segment gets an instruction and a max_turns.
     - max_turns doesn't apply for a single agent.
  
4. Tool

1. name
2. description
3. parameters: dict - ++**[JSON schema](https://json-schema.org/)**++ defining the function’s input arguments
4. function: Callable

  
5. Eval

1.  output_type (default: Critique(BaseModel): feedback: str. 
2. __.call._: Callable. This function uses the output type from the llm and aggregates the scores and introduces a property passed: bool to the output_type.
3. eval_func: Agent | Callable. By default the evaluator is an llm judge agent, i'm thinking we should make it either an agent or a function (code evals). The aggregator(call dunder) (i think we can find better pythonic names for all of these methods) then passes the values to the eval result type.

