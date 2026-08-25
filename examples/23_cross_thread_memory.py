import asyncio

from super_harness import MemoryManager, SQLiteMemoryStore


async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store)
    fragments = await manager.retrieve_context("preferred editor", current_thread_id="thread-b")
    for fragment in fragments:
        print(fragment.source, fragment.content)
    await store.close()


asyncio.run(main())
