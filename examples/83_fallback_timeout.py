"""Apply a bounded timeout per provider attempt."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackPolicy, FallbackProvider
from super_harness.models import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class SlowProvider:
    name = "slow"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        await asyncio.sleep(10)
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


async def main() -> None:
    try:
        await FallbackProvider((SlowProvider(),), policy=FallbackPolicy(timeout=0.01)).complete(ModelRequest(()))
    except Exception as error:
        print(type(error).__name__, str(error))


asyncio.run(main())
