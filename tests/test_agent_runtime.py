from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from super_harness import Agent
from super_harness import tool as define_tool
from super_harness.exceptions import ToolError
from super_harness.models import (
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
    Usage,
)
from super_harness.runtime import TurnStatus


class RecordingProvider:
    name = "recording"
    capabilities = ModelCapabilities()

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(self.responses.pop(0))

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        text = self.responses.pop(0)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        for part in text.split("|"):
            yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta=part)
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(text.replace("|", ""), usage=Usage(2, 3, 5)),
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_multi_turn_history_and_lifecycle_events() -> None:
    provider = RecordingProvider(["first", "sec|ond"])
    thread = Agent(provider, instructions="Be concise").thread()

    first = await thread.arun("one")
    events = [event async for event in thread.astream("two")]

    assert first.text == "first"
    assert [event.type for event in events] == [
        "turn.started",
        "model.started",
        "model.text.delta",
        "model.text.delta",
        "model.completed",
        "turn.completed",
    ]
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    ]
    assert len(thread.turns) == 2
    assert all(turn.status is TurnStatus.COMPLETED for turn in thread.turns)


def test_sync_run() -> None:
    provider = RecordingProvider(["hello"])
    assert Agent(provider).run("hi").text == "hello"


@pytest.mark.asyncio
async def test_sync_run_rejected_inside_event_loop() -> None:
    provider = RecordingProvider(["unused"])
    with pytest.raises(RuntimeError, match="active event loop"):
        Agent(provider).run("hi")


class FailingProvider(RecordingProvider):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        raise ValueError("provider broke")


class IncompleteProvider(RecordingProvider):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta="partial")


@pytest.mark.asyncio
async def test_provider_failure_marks_turn_failed() -> None:
    thread = Agent(FailingProvider([])).thread()
    events: list[str] = []
    with pytest.raises(ValueError, match="provider broke"):
        async for event in thread.astream("hi"):
            events.append(event.type)
    assert events == ["turn.started", "model.started", "turn.failed"]
    assert thread.turns[0].status is TurnStatus.FAILED
    assert thread.turns[0].error == "provider broke"


@pytest.mark.asyncio
async def test_runtime_rejects_provider_stream_without_completion() -> None:
    thread = Agent(IncompleteProvider([])).thread()
    events: list[str] = []
    with pytest.raises(RuntimeError, match="without a completed event"):
        async for event in thread.astream("hi"):
            events.append(event.type)
    assert events[-1] == "turn.failed"
    assert thread.turns[0].status is TurnStatus.FAILED


class BlockingProvider(RecordingProvider):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        await asyncio.Event().wait()
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED)


@pytest.mark.asyncio
async def test_cancellation_marks_turn_cancelled() -> None:
    thread = Agent(BlockingProvider([])).thread()

    async def consume() -> None:
        async for _ in thread.astream("wait"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert thread.turns[0].status is TurnStatus.CANCELLED


class ToolLoopProvider(RecordingProvider):
    def __init__(self, *, repeat_call: bool = False) -> None:
        super().__init__([])
        self.repeat_call = repeat_call

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if len(self.requests) == 1 or self.repeat_call:
            call = ToolCall("call_add", "add", {"left": 20, "right": 22}, '{"left":20,"right":22}')
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(tool_calls=(call,)),
            )
        else:
            yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta="42")
            yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("42"))


class ParallelToolProvider(RecordingProvider):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if len(self.requests) == 1:
            calls = (
                ToolCall("call_1", "pause", {"value": 1}, '{"value":1}'),
                ToolCall("call_2", "pause", {"value": 2}, '{"value":2}'),
            )
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(tool_calls=calls),
            )
        else:
            yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("done"))


@pytest.mark.asyncio
async def test_agent_executes_tool_loop_and_correlates_events() -> None:
    @define_tool
    def add(left: int, right: int) -> int:
        """Add two integers."""

        return left + right

    provider = ToolLoopProvider()
    thread = Agent(provider, tools=[add]).thread()
    events = [event async for event in thread.astream("calculate")]

    assert thread.turns[0].response is not None
    assert thread.turns[0].response.text == "42"
    assert [event.type for event in events].count("model.started") == 2
    assert [event.type for event in events].count("tool.started") == 1
    tool_completed = next(event for event in events if event.type == "tool.completed")
    assert tool_completed.tool_call_id == "call_add"
    assert tool_completed.payload["success"] is True
    assert [message.role for message in provider.requests[1].messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
    ]
    assert provider.requests[1].messages[-1].content == "42"


@pytest.mark.asyncio
async def test_tool_loop_step_budget_fails_turn() -> None:
    @define_tool
    def add(left: int, right: int) -> int:
        return left + right

    thread = Agent(ToolLoopProvider(repeat_call=True), tools=[add], max_model_steps=2).thread()
    with pytest.raises(ToolError, match="exceeded maximum"):
        await thread.arun("loop forever")
    assert thread.turns[0].status is TurnStatus.FAILED


@pytest.mark.asyncio
async def test_parallel_safe_tools_execute_concurrently() -> None:
    active = 0
    max_active = 0

    @define_tool(supports_parallel=True)
    async def pause(value: int) -> int:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.15)
        active -= 1
        return value

    thread = Agent(ParallelToolProvider([]), tools=[pause]).thread()
    response = await thread.arun("run both")

    assert response.text == "done"
    assert max_active == 2
