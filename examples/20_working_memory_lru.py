from super_harness import WorkingMemory

memory = WorkingMemory(max_items=2)
memory.set("first", 1)
memory.set("second", 2)
memory.get("first")
memory.set("third", 3)
print(memory.snapshot())  # first and third remain
