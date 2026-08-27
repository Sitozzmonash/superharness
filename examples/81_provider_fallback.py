"""Fall back after an explicit provider failure."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackProvider
from super_harness.exceptions import ModelError
from super_harness.models import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class Provider:
    capabilities = ModelCapabilities()

    def __init__(self, name: str, answer: str = "") -> None:
        self.name, self.answer = name, answer

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.answer:
            raise ModelError("unavailable")
        return ModelResponse(text=self.answer)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


print(asyncio.run(FallbackProvider((Provider("primary"), Provider("backup", "ok"))).complete(ModelRequest(()))).text)
