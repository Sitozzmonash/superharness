import asyncio

from super_harness import MemoryCandidate, SQLiteMemoryStore


async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    await store.remember(MemoryCandidate("Release requires a canary"), source_thread_id="thread-a")
    print(await store.search("release canary"))
    await store.close()


asyncio.run(main())
