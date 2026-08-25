import asyncio

from super_harness import MemoryManager, SQLiteMemoryStore
from super_harness.models import Message, MessageRole


async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store)
    records = await manager.consolidate(
        "thread-a", [Message(MessageRole.USER, "Remember: use jasmine tea")]
    )
    print(records)
    await store.close()


asyncio.run(main())
