"""Streaming-first in-memory Thread runtime."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeVar
from uuid import uuid4

from super_harness.exceptions import ToolError
from super_harness.models import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    ModelStreamEventType,
    ToolDefinition,
)
from super_harness.tools import ToolExecutor, ToolRegistry, ToolResult

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
    tool_registry: ToolRegistry | None = None
    tool_executor: ToolExecutor | None = None
    max_model_steps: int = 8
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
        definitions = list(tools)
        if self.tool_registry is not None:
            definitions.extend(self.tool_registry.definitions())
        return ModelRequest(messages, tools=definitions, output_schema=output_schema)

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
            for step in range(1, self.max_model_steps + 1):
                response: ModelResponse | None = None
                request = self._request(tools=tools, output_schema=output_schema)
                async for model_event in self.provider.stream(request):
                    if model_event.type is ModelStreamEventType.STARTED:
                        yield Event(
                            "model.started",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            payload={"provider": self.provider.name, "step": step},
                        )
                    elif model_event.type is ModelStreamEventType.TEXT_DELTA:
                        yield Event(
                            "model.text.delta",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            payload={"delta": model_event.delta, "step": step},
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
                                "step": step,
                            },
                        )
                    elif model_event.type is ModelStreamEventType.COMPLETED:
                        response = model_event.response
                        if response is None:
                            raise RuntimeError("provider completed without a normalized response")
                        yield Event(
                            "model.completed",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            payload={
                                "response": response,
                                "usage": response.usage,
                                "tool_calls": response.tool_calls,
                                "step": step,
                            },
                        )
                        break
                if response is None:
                    raise RuntimeError("provider stream ended without a completed event")
                if response.tool_calls and self.tool_executor is not None:
                    self.messages.append(
                        Message(
                            MessageRole.ASSISTANT,
                            response.text,
                            tool_calls=response.tool_calls,
                        )
                    )
                    turn.status = TurnStatus.WAITING_TOOL
                    registry = self.tool_registry
                    parallel = len(response.tool_calls) > 1 and registry is not None
                    if parallel and registry is not None:
                        try:
                            parallel = all(
                                registry.get(call.name).metadata.supports_parallel
                                for call in response.tool_calls
                            )
                        except ToolError:
                            parallel = False
                    for call in response.tool_calls:
                        yield Event(
                            "tool.started",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            tool_call_id=call.call_id,
                            payload={"name": call.name, "arguments": call.arguments},
                        )
                    results: list[ToolResult]
                    if parallel:
                        results = await asyncio.gather(
                            *(self.tool_executor.execute(call) for call in response.tool_calls)
                        )
                    else:
                        results = []
                        for call in response.tool_calls:
                            results.append(await self.tool_executor.execute(call))
                    for call, result in zip(response.tool_calls, results, strict=True):
                        self.messages.append(
                            Message(
                                MessageRole.TOOL,
                                result.output,
                                name=result.name,
                                tool_call_id=result.call_id,
                            )
                        )
                        yield Event(
                            "tool.completed",
                            thread_id=self.thread_id,
                            turn_id=turn.turn_id,
                            tool_call_id=call.call_id,
                            payload={"result": result, "success": result.success},
                        )
                    turn.status = TurnStatus.RUNNING
                    continue
                turn.complete(response)
                if response.text or response.tool_calls:
                    self.messages.append(
                        Message(
                            MessageRole.ASSISTANT,
                            response.text,
                            tool_calls=response.tool_calls,
                        )
                    )
                self.updated_at = datetime.now(UTC)
                yield Event(
                    "turn.completed",
                    thread_id=self.thread_id,
                    turn_id=turn.turn_id,
                    payload={"response": response},
                )
                break
            if turn.status in {TurnStatus.RUNNING, TurnStatus.WAITING_TOOL}:
                raise ToolError(f"tool loop exceeded maximum of {self.max_model_steps} model steps")
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
