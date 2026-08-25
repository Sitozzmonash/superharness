"""Persist, reopen, resume, and fork a Thread."""

import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from super_harness import Agent, SQLiteThreadStore
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class LocalProvider:
    name = "local"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("saved")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("saved"))

    async def aclose(self) -> None:
        return None


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "threads.db"
        with SQLiteThreadStore(database) as store:
            agent = Agent(LocalProvider(), store=store)
            thread = agent.thread()
            await thread.arun("remember this")
            thread_id = thread.thread_id

        with SQLiteThreadStore(database) as store:
            agent = Agent(LocalProvider(), store=store)
            resumed = agent.resume(thread_id)
            forked = resumed.fork()
            print(resumed.thread_id, resumed.messages[-1].content)
            print("fork", forked.thread_id, "parent", forked.parent_thread_id)


if __name__ == "__main__":
    asyncio.run(main())
