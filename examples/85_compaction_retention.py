"""Retain the newest messages while summarizing an older prefix."""

from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import Message, MessageRole, ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


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
thread.messages.extend(Message(MessageRole.USER, f"message {index}") for index in range(8))
thread.compact(retain_messages=2)
print(thread.summaries[-1].summarized_messages, len(thread.messages))
