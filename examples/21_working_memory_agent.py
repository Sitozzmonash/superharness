from super_harness import Agent, DeepSeekProvider, WorkingMemory

memory = WorkingMemory()
memory.set("response_language", "Chinese")
fragment = memory.context()
agent = Agent(DeepSeekProvider(), context=(() if fragment is None else (fragment,)))
print(agent.run("Introduce this project briefly.").text)
