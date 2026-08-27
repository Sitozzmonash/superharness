"""Compact old messages with an application-provided summary."""

from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)


class OfflineProvider:
    name = "offline"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


thread = Agent(OfflineProvider()).thread()
thread.messages.extend(
    (
        Message(MessageRole.USER, "Remember release policy"),
        Message(MessageRole.ASSISTANT, "Recorded"),
    )
)
print([event.type for event in thread.compact("Release policy was recorded.", retain_messages=1)])
