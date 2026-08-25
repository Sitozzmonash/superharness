"""Public Agent API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any

from super_harness.models import ModelProvider, ModelResponse, ToolDefinition
from super_harness.runtime.events import Event
from super_harness.runtime.thread import Thread


class Agent:
    """A configured agent that creates independent conversational Threads."""

    def __init__(self, provider: ModelProvider, *, instructions: str | None = None) -> None:
        self.provider = provider
        self.instructions = instructions

    def thread(self) -> Thread:
        return Thread(provider=self.provider, instructions=self.instructions)

    async def arun(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        return await self.thread().arun(input, tools=tools, output_schema=output_schema)

    def run(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        return self.thread().run(input, tools=tools, output_schema=output_schema)

    def astream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        return self.thread().astream(input, tools=tools, output_schema=output_schema)

    def stream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> Iterator[Event]:
        return self.thread().stream(input, tools=tools, output_schema=output_schema)

    async def aclose(self) -> None:
        await self.provider.aclose()
