from super_harness import WorkingMemory

memory = WorkingMemory(max_items=3)
memory.set("goal", "ship Phase 5")
memory.set("branch", "main")
print(memory.snapshot())
print(memory.context())
