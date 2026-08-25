"""Active Turn event and control handle."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from super_harness.models import ModelResponse, ToolDefinition

from .events import Event

if TYPE_CHECKING:
    from .thread import Thread


_DONE = object()


class TurnHandle:
    def __init__(
        self,
        thread: Thread,
        input: str,
        *,
        tools: Sequence[ToolDefinition] = (),
        output_schema: Mapping[str, Any] | None = None,
    ) -> None:
        self.thread = thread
        self.turn_id: str | None = None
        self._ready = asyncio.Event()
        self._queue: asyncio.Queue[Event | object] = asyncio.Queue()
        self._error: BaseException | None = None
        self._task = asyncio.create_task(self._pump(input, tools, output_schema))

    async def _pump(
        self,
        input: str,
        tools: Sequence[ToolDefinition],
        output_schema: Mapping[str, Any] | None,
    ) -> None:
        try:
            async for event in self.thread.astream(input, tools=tools, output_schema=output_schema):
                if self.turn_id is None and event.turn_id is not None:
                    self.turn_id = event.turn_id
                    self._ready.set()
                await self._queue.put(event)
        except BaseException as exc:
            self._error = exc
        finally:
            self._ready.set()
            await self._queue.put(_DONE)

    async def events(self) -> AsyncIterator[Event]:
        while True:
            item = await self._queue.get()
            if item is _DONE:
                break
            if isinstance(item, Event):
                yield item
        if self._error is not None:
            raise self._error

    async def wait(self) -> ModelResponse:
        await self._task
        if self._error is not None:
            raise self._error
        if self.turn_id is None:
            raise RuntimeError("turn did not start")
        turn = next(item for item in self.thread.turns if item.turn_id == self.turn_id)
        if turn.response is None:
            raise RuntimeError(f"turn ended with status {turn.status.value}")
        return turn.response

    async def steer(self, instruction: str) -> None:
        if not instruction.strip():
            raise ValueError("steering instruction must be non-empty")
        await self._ready.wait()
        if self.turn_id is None or self._task.done():
            raise RuntimeError("turn is no longer active")
        self.thread.queue_steering(self.turn_id, instruction)

    def cancel(self) -> None:
        self._task.cancel()

    async def interrupt(self) -> None:
        await self._ready.wait()
        if self.turn_id is None or self._task.done():
            raise RuntimeError("turn is no longer active")
        self.thread.request_interrupt(self.turn_id)
        self._task.cancel()
