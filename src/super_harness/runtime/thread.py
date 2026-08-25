"""Streaming-first in-memory Thread runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import uuid4

from super_harness.models import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelStreamEventType,
    ToolDefinition,
)

from .events import Event
from .turn import Turn, TurnStatus

T = TypeVar("T")


def _message_list() -> list[Message]:
    return []


def _turn_list() -> list[Turn]:
    return []


def _sync(operation: AsyncIterator[T]) -> list[T]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:

        async def collect() -> list[T]:
            return [item async for item in operation]

        return asyncio.run(collect())
    raise RuntimeError("sync API cannot run inside an active event loop; use the async API")


@dataclass(slots=True)
class Thread:
    """Ordered conversation history and turns for one Agent session."""

    provider: ModelProvider
    instructions: str | None = None
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    messages: list[Message] = field(default_factory=_message_list)
    turns: list[Turn] = field(default_factory=_turn_list)

    def _request(
        self,
        *,
        tools: Sequence[ToolDefinition],
        output_schema: Mapping[str, Any] | None,
    ) -> ModelRequest:
        messages: list[Message] = []
        if self.instructions:
            messages.append(Message(MessageRole.SYSTEM, self.instructions))
        messages.extend(self.messages)
        return ModelRequest(messages, tools=tools, output_schema=output_schema)

    async def astream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        if not input.strip():
            raise ValueError("turn input must be non-empty")
        turn = Turn(input)
        self.turns.append(turn)
        self.messages.append(Message(MessageRole.USER, input))
        self.updated_at = datetime.now(UTC)
        turn.start()
        yield Event("turn.started", thread_id=self.thread_id, turn_id=turn.turn_id)
        try:
            request = self._request(tools=tools, output_schema=output_schema)
            async for model_event in self.provider.stream(request):
                if model_event.type is ModelStreamEventType.STARTED:
                    yield Event(
                        "model.started",
                        thread_id=self.thread_id,
                        turn_id=turn.turn_id,
                        payload={"provider": self.provider.name},
                    )
                elif model_event.type is ModelStreamEventType.TEXT_DELTA:
                    yield Event(
                        "model.text.delta",
                        thread_id=self.thread_id,
                        turn_id=turn.turn_id,
                        payload={"delta": model_event.delta},
                    )
                elif model_event.type is ModelStreamEventType.TOOL_CALL_DELTA:
                    yield Event(
                        "model.tool_call.delta",
                        thread_id=self.thread_id,
                        turn_id=turn.turn_id,
                        tool_call_id=model_event.tool_call_id,
                        payload={
                            "index": model_event.tool_call_index,
                            "name": model_event.tool_name,
                            "delta": model_event.delta,
                        },
                    )
                elif model_event.type is ModelStreamEventType.COMPLETED:
                    response = model_event.response
                    if response is None:
                        raise RuntimeError("provider completed without a normalized response")
                    turn.complete(response)
                    if response.text:
                        self.messages.append(Message(MessageRole.ASSISTANT, response.text))
                    self.updated_at = datetime.now(UTC)
                    yield Event(
                        "model.completed",
                        thread_id=self.thread_id,
                        turn_id=turn.turn_id,
                        payload={
                            "response": response,
                            "usage": response.usage,
                            "tool_calls": response.tool_calls,
                        },
                    )
                    yield Event(
                        "turn.completed",
                        thread_id=self.thread_id,
                        turn_id=turn.turn_id,
                        payload={"response": response},
                    )
                    break
            if turn.status is TurnStatus.RUNNING:
                raise RuntimeError("provider stream ended without a completed event")
        except asyncio.CancelledError:
            turn.cancel()
            self.updated_at = datetime.now(UTC)
            raise
        except Exception as exc:
            turn.fail(exc)
            self.updated_at = datetime.now(UTC)
            yield Event(
                "turn.failed",
                thread_id=self.thread_id,
                turn_id=turn.turn_id,
                payload={"error_type": type(exc).__name__, "message": str(exc)},
            )
            raise

    async def arun(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        response: ModelResponse | None = None
        async for event in self.astream(input, tools=tools, output_schema=output_schema):
            if event.type == "turn.completed":
                candidate = event.payload.get("response")
                if isinstance(candidate, ModelResponse):
                    response = candidate
        if response is None:
            raise RuntimeError("turn ended without a response")
        return response

    def stream(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> Iterator[Event]:
        return iter(_sync(self.astream(input, tools=tools, output_schema=output_schema)))

    def run(
        self,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> ModelResponse:
        response: ModelResponse | None = None
        for event in self.stream(input, tools=tools, output_schema=output_schema):
            if event.type == "turn.completed":
                candidate = event.payload.get("response")
                if isinstance(candidate, ModelResponse):
                    response = candidate
        if response is None:
            raise RuntimeError("turn ended without a response")
        return response
