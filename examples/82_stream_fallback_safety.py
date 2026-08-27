"""Stream from a backup only when the first provider emitted no visible output."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackProvider
from super_harness.exceptions import ModelError
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class StreamProvider:
    capabilities = ModelCapabilities()

    def __init__(self, name: str, fail: bool) -> None:
        self.name, self.fail = name, fail

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if self.fail:
            raise ModelError("before output")
        response = ModelResponse(text="safe")
        yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta="safe")
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=response)

    async def aclose(self) -> None:
        pass


async def main() -> None:
    provider = FallbackProvider((StreamProvider("primary", True), StreamProvider("backup", False)))
    print([event.type async for event in provider.stream(ModelRequest(()))])


asyncio.run(main())
