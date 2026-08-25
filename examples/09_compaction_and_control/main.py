"""Compact history and interrupt an active TurnHandle."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class BlockingProvider:
    name = "blocking"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        return None


async def main() -> None:
    thread = Agent(BlockingProvider()).thread()
    thread.messages.extend(Message(MessageRole.USER, f"old message {index}") for index in range(12))
    for event in thread.compact(retain_messages=3):
        print(event.type, dict(event.payload))

    handle = thread.start("long operation")
    iterator = handle.events().__aiter__()
    print((await anext(iterator)).type)
    await handle.interrupt()
    try:
        async for event in iterator:
            print(event.type)
    except asyncio.CancelledError:
        print("turn interrupted")


if __name__ == "__main__":
    asyncio.run(main())
