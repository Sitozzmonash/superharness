from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from super_harness import (
    Agent,
    HookContext,
    HookEvent,
    HookFailurePolicy,
    HookRegistry,
    HookResult,
    HookTrace,
    tool,
)
from super_harness.exceptions import HookError
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
)


class HookProvider:
    name = "hook-provider"
    capabilities = ModelCapabilities()

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("done")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if len(self.requests) == 1 and request.tools:
            call = ToolCall("call_1", "echo", {"text": "original"}, '{"text":"original"}')
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED, response=ModelResponse(tool_calls=(call,))
            )
        else:
            yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("done"))

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_all_hook_events_are_ordered_observable_and_modification_is_explicit() -> None:
    traces: list[HookTrace] = []
    registry = HookRegistry(trace_sink=traces.append)
    seen: list[str] = []

    async def first(context: HookContext) -> HookResult:
        seen.append(f"first:{context.event.value}")
        return HookResult.enrich(value=2)

    def second(context: HookContext) -> None:
        seen.append(f"second:{context.data.get('value')}")

    for event in HookEvent:
        registry.register(event, first, name=f"first-{event.value}", priority=1, allow_modify=True)
        registry.register(event, second, name=f"second-{event.value}", priority=2)
        outcome = await registry.dispatch(HookContext(event, {"value": 1}))
        assert outcome.data["value"] == 2

    assert len(seen) == len(HookEvent) * 2
    assert len(traces) == len(HookEvent) * 2
    assert all(trace.success for trace in traces)


@pytest.mark.asyncio
async def test_hook_failure_policies_timeout_denial_and_cancellation() -> None:
    registry = HookRegistry()

    def broken(context: HookContext) -> None:
        raise RuntimeError(context.event.value)

    registry.register(
        HookEvent.SESSION_START,
        broken,
        failure_policy=HookFailurePolicy.WARN,
    )
    with pytest.warns(RuntimeWarning, match="hook runtime:broken failed"):
        outcome = await registry.dispatch(HookContext(HookEvent.SESSION_START))
    assert not outcome.traces[0].success
    assert "RuntimeError" in (outcome.traces[0].warning or "")

    open_registry = HookRegistry()
    open_registry.register(
        HookEvent.TURN_START,
        broken,
        failure_policy=HookFailurePolicy.FAIL_OPEN,
    )
    assert not (await open_registry.dispatch(HookContext(HookEvent.TURN_START))).traces[0].success

    async def slow(context: HookContext) -> None:
        await asyncio.sleep(1)

    closed = HookRegistry()
    closed.register(
        HookEvent.BEFORE_MODEL,
        slow,
        timeout=0.01,
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    with pytest.raises(HookError, match="failed closed"):
        await closed.dispatch(HookContext(HookEvent.BEFORE_MODEL))

    denied = HookRegistry()
    denied.register(HookEvent.PRE_TOOL_USE, lambda _: HookResult.deny("policy blocked"))
    result = await denied.dispatch(HookContext(HookEvent.PRE_TOOL_USE))
    assert result.denied and result.deny_reason == "policy blocked"

    cancellable = HookRegistry()
    cancellable.register(HookEvent.AFTER_MODEL, slow, timeout=10)
    task = asyncio.create_task(cancellable.dispatch(HookContext(HookEvent.AFTER_MODEL)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_runtime_and_tool_pipeline_dispatch_hooks() -> None:
    registry = HookRegistry()
    events: list[HookEvent] = []

    def observe(context: HookContext) -> None:
        events.append(context.event)

    def rewrite_tool(context: HookContext) -> HookResult:
        arguments = dict(context.data["arguments"])
        arguments["text"] = "modified"
        return HookResult.enrich(arguments=arguments)

    for event in (
        HookEvent.SESSION_START,
        HookEvent.USER_PROMPT,
        HookEvent.TURN_START,
        HookEvent.BEFORE_MODEL,
        HookEvent.AFTER_MODEL,
        HookEvent.POST_TOOL_USE,
        HookEvent.TURN_END,
        HookEvent.SESSION_END,
    ):
        registry.register(event, observe)
    registry.register(HookEvent.PRE_TOOL_USE, rewrite_tool, allow_modify=True)

    values: list[str] = []

    @tool
    def echo(text: str) -> str:
        values.append(text)
        return text

    thread = Agent(HookProvider(), tools=[echo], hooks=registry).thread()
    response = await thread.arun("run")
    await thread.aclose()

    assert response.text == "done"
    assert values == ["modified"]
    assert events.count(HookEvent.BEFORE_MODEL) == 2
    assert HookEvent.POST_TOOL_USE in events
    assert events[0] is HookEvent.SESSION_START
    assert events[-1] is HookEvent.SESSION_END


@pytest.mark.asyncio
async def test_error_and_compaction_hooks() -> None:
    registry = HookRegistry()
    seen: list[HookEvent] = []

    def observe(context: HookContext) -> None:
        seen.append(context.event)

    registry.register(HookEvent.PRE_COMPACT, observe)
    registry.register(HookEvent.POST_COMPACT, observe)
    registry.register(HookEvent.ERROR, observe)
    thread = Agent(HookProvider(), hooks=registry).thread()
    await thread.acompact()

    def deny_model(context: HookContext) -> HookResult:
        return HookResult.deny("no model")

    registry.register(HookEvent.BEFORE_MODEL, deny_model)
    with pytest.raises(HookError, match="no model"):
        await thread.arun("blocked")
    assert seen == [HookEvent.PRE_COMPACT, HookEvent.POST_COMPACT, HookEvent.ERROR]
