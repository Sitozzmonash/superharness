from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from super_harness import (
    Agent,
    AgentManager,
    AgentStatus,
    ContextFragment,
    ContextInheritance,
    ContextKind,
    HookContext,
    HookEvent,
    HookFailurePolicy,
    HookRegistry,
    MultiAgentLimits,
    SpawnRequest,
)
from super_harness.exceptions import MultiAgentError
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
    Usage,
)


@dataclass
class TeamState:
    active: int = 0
    max_active: int = 0


class TeamProvider:
    name = "team"
    capabilities = ModelCapabilities()

    def __init__(self, state: TeamState, *, delay: float = 0.01, tokens: int = 3) -> None:
        self.state = state
        self.delay = delay
        self.tokens = tokens
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        prompt = request.messages[-1].content
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        self.state.active += 1
        self.state.max_active = max(self.state.max_active, self.state.active)
        try:
            if "fail" in prompt:
                raise RuntimeError("child failed")
            if "block" in prompt:
                await asyncio.Event().wait()
            await asyncio.sleep(self.delay)
            yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta="hidden-child-delta")
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(f"result:{prompt}", usage=Usage(1, 2, self.tokens)),
            )
        finally:
            self.state.active -= 1

    async def aclose(self) -> None:
        return None


class OrchestratorProvider:
    name = "orchestrator"
    capabilities = ModelCapabilities()

    def __init__(self) -> None:
        self.step = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.step += 1
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if self.step == 1:
            assert {item.name for item in request.tools} >= {"spawn_agent", "wait_agent"}
            call = ToolCall(
                "spawn_1",
                "spawn_agent",
                {"task": "delegated research", "role": "researcher"},
                '{"task":"delegated research","role":"researcher"}',
            )
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED, response=ModelResponse(tool_calls=(call,))
            )
            return
        tool_output = json.loads(request.messages[-1].content)
        if self.step == 2:
            call = ToolCall(
                "wait_1",
                "wait_agent",
                {"agent_ids": [tool_output["agent_id"]], "timeout": 1.0},
                json.dumps({"agent_ids": [tool_output["agent_id"]], "timeout": 1.0}),
            )
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED, response=ModelResponse(tool_calls=(call,))
            )
            return
        assert tool_output[0]["status"] == "completed"
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse("root aggregated delegated research"),
        )

    async def aclose(self) -> None:
        return None


def _manager(
    *,
    limits: MultiAgentLimits | None = None,
    state: TeamState | None = None,
    hooks: HookRegistry | None = None,
    requests: list[SpawnRequest] | None = None,
    tokens: int = 3,
) -> tuple[AgentManager, TeamState]:
    shared = state or TeamState()

    def factory(request: SpawnRequest) -> Agent:
        if requests is not None:
            requests.append(request)
        return Agent(
            TeamProvider(shared, delay=0.02, tokens=tokens),
            instructions=request.instructions,
            context=request.inherited_context,
        )

    root = Agent(TeamProvider(shared))
    return AgentManager(root, factory, limits=limits, hooks=hooks), shared


@pytest.mark.asyncio
async def test_spawn_three_concurrently_selective_wait_aggregate_and_trace_tree() -> None:
    manager, state = _manager()
    children = [
        await manager.spawn_agent(manager.root_agent_id, f"task-{index}", role=f"worker-{index}")
        for index in range(3)
    ]
    selected = await manager.wait([children[0].agent_id], timeout=1)
    assert selected[0].status is AgentStatus.COMPLETED
    completed = await manager.wait_all([item.agent_id for item in children], timeout=1)

    assert all(item.status is AgentStatus.COMPLETED for item in completed)
    assert state.max_active == 3
    assert [result.text for result in manager.results()] == [
        "result:task-0",
        "result:task-1",
        "result:task-2",
    ]
    root = manager.get(manager.root_agent_id)
    assert root.child_agent_ids == tuple(item.agent_id for item in children)
    events = manager.event_history()
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert {event.type for event in events} >= {
        "agent.spawned",
        "agent.started",
        "agent.event",
        "agent.completed",
    }
    assert all(
        event.payload.get("event_type") != "model.text.delta"
        for event in events
        if event.type == "agent.event"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_model_autonomously_spawns_waits_and_aggregates_via_tools() -> None:
    state = TeamState()

    def factory(request: SpawnRequest) -> Agent:
        return Agent(TeamProvider(state), context=request.inherited_context)

    manager = AgentManager(Agent(OrchestratorProvider()), factory)
    response = await manager.thread(manager.root_agent_id).arun("delegate this research")
    children = manager.list_agents(parent_agent_id=manager.root_agent_id)

    assert response.text == "root aggregated delegated research"
    assert len(children) == 1
    assert children[0].role == "researcher"
    assert children[0].status is AgentStatus.COMPLETED


@pytest.mark.asyncio
async def test_send_resume_close_and_structured_result() -> None:
    manager, _ = _manager()
    child = await manager.spawn_agent(manager.root_agent_id, "first", role="researcher")
    await manager.wait_all([child.agent_id], timeout=1)
    queued = await manager.send_input(child.agent_id, "follow-up")
    assert queued.queued_messages == ("follow-up",)
    resumed = await manager.resume_agent(child.agent_id)
    assert resumed.status in {AgentStatus.PENDING, AgentStatus.RUNNING}
    final = (await manager.wait_all([child.agent_id], timeout=1))[0]
    assert final.result is not None and final.result.text == "result:follow-up"
    assert manager.get(child.agent_id).turn_count == 2

    closed = await manager.close_agent(child.agent_id)
    assert closed.status is AgentStatus.CLOSED
    await manager.send_input(child.agent_id, "after close")
    await manager.resume_agent(child.agent_id)
    assert (await manager.wait_all([child.agent_id], timeout=1))[0].status is AgentStatus.COMPLETED


@pytest.mark.asyncio
async def test_interrupt_and_parent_cancel_propagate_to_subtree() -> None:
    manager, _ = _manager()
    interrupted = await manager.spawn_agent(manager.root_agent_id, "block-one")
    await asyncio.sleep(0.02)
    snapshot = await manager.interrupt_agent(interrupted.agent_id)
    assert snapshot.status is AgentStatus.INTERRUPTED

    parent = await manager.spawn_agent(manager.root_agent_id, "block-parent")
    child = await manager.spawn_agent(parent.agent_id, "block-child")
    await asyncio.sleep(0.02)
    await manager.cancel(parent.agent_id)
    assert manager.get(parent.agent_id).status is AgentStatus.CANCELLED
    assert manager.get(child.agent_id).status is AgentStatus.CANCELLED


@pytest.mark.asyncio
async def test_depth_active_total_timeout_failure_and_budget_guards() -> None:
    limits = MultiAgentLimits(
        max_active_agents=1,
        max_total_agents=3,
        max_depth=1,
        total_token_budget=4,
        total_timeout=10,
        default_agent_timeout=0.03,
    )
    manager, _ = _manager(limits=limits, tokens=5)
    blocking = await manager.spawn_agent(manager.root_agent_id, "block")
    with pytest.raises(MultiAgentError, match="active agent limit"):
        await manager.spawn_agent(manager.root_agent_id, "second")
    timed = (await manager.wait_all([blocking.agent_id], timeout=1))[0]
    assert timed.status is AgentStatus.FAILED
    assert timed.result is not None and timed.result.error == "agent timed out"

    budgeted = await manager.spawn_agent(manager.root_agent_id, "budget", timeout=0.5)
    budgeted = (await manager.wait_all([budgeted.agent_id], timeout=1))[0]
    assert budgeted.status is AgentStatus.BUDGET_EXHAUSTED
    assert manager.tokens_used == 5
    with pytest.raises(MultiAgentError, match="token budget"):
        await manager.spawn_agent(manager.root_agent_id, "too-late")

    depth_manager, _ = _manager(limits=MultiAgentLimits(max_depth=1))
    parent = await depth_manager.spawn_agent(depth_manager.root_agent_id, "task")
    with pytest.raises(MultiAgentError, match="depth limit"):
        await depth_manager.spawn_agent(parent.agent_id, "grandchild")
    await depth_manager.wait_all([parent.agent_id], timeout=1)

    total_manager, _ = _manager(limits=MultiAgentLimits(max_total_agents=1))
    only = await total_manager.spawn_agent(total_manager.root_agent_id, "only")
    await total_manager.wait_all([only.agent_id], timeout=1)
    with pytest.raises(MultiAgentError, match="total agent limit"):
        await total_manager.spawn_agent(total_manager.root_agent_id, "extra")

    failure_manager, _ = _manager()
    failed = await failure_manager.spawn_agent(failure_manager.root_agent_id, "fail-now")
    failed = (await failure_manager.wait_all([failed.agent_id], timeout=1))[0]
    assert failed.status is AgentStatus.FAILED
    assert failed.result is not None and "RuntimeError" in (failed.result.error or "")


@pytest.mark.asyncio
async def test_context_inheritance_and_subagent_hooks() -> None:
    requests: list[SpawnRequest] = []
    hook_events: list[HookEvent] = []
    hooks = HookRegistry()

    def observe(context: HookContext) -> None:
        hook_events.append(context.event)

    hooks.register(HookEvent.SUBAGENT_START, observe)
    hooks.register(HookEvent.SUBAGENT_END, observe)
    manager, _ = _manager(requests=requests, hooks=hooks)
    root_thread = manager.thread(manager.root_agent_id)
    root_thread.context.extend(
        [
            ContextFragment(ContextKind.DEVELOPER, "rules", "rules"),
            ContextFragment(ContextKind.RAG, "evidence", "rag"),
        ]
    )
    root_thread.messages.append(Message(MessageRole.USER, "prior conversation"))

    minimal = await manager.spawn_agent(
        manager.root_agent_id, "minimal", inheritance=ContextInheritance.MINIMAL
    )
    selected = await manager.spawn_agent(
        manager.root_agent_id,
        "selected",
        inheritance=ContextInheritance.SELECTED,
        selected_sources=("rag",),
    )
    full = await manager.spawn_agent(
        manager.root_agent_id, "full", inheritance=ContextInheritance.FULL
    )
    await manager.wait_all([minimal.agent_id, selected.agent_id, full.agent_id], timeout=1)

    assert requests[0].inherited_context == ()
    assert [item.source for item in requests[1].inherited_context] == ["rag"]
    assert {item.source for item in requests[2].inherited_context} == {
        "rules",
        "rag",
        f"agent:{manager.root_agent_id}:history",
    }
    assert hook_events.count(HookEvent.SUBAGENT_START) == 3
    assert hook_events.count(HookEvent.SUBAGENT_END) == 3


@pytest.mark.asyncio
async def test_subagent_hook_failure_does_not_orphan_or_block_wait() -> None:
    start_hooks = HookRegistry()

    def fail(context: HookContext) -> None:
        raise RuntimeError(context.event.value)

    start_hooks.register(
        HookEvent.SUBAGENT_START,
        fail,
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    start_manager, _ = _manager(hooks=start_hooks)
    with pytest.raises(MultiAgentError, match="start hook"):
        await start_manager.spawn_agent(start_manager.root_agent_id, "task")
    assert len(start_manager.list_agents()) == 1

    end_hooks = HookRegistry()
    end_hooks.register(
        HookEvent.SUBAGENT_END,
        fail,
        failure_policy=HookFailurePolicy.FAIL_CLOSED,
    )
    end_manager, _ = _manager(hooks=end_hooks)
    child = await end_manager.spawn_agent(end_manager.root_agent_id, "task")
    finished = (await end_manager.wait_all([child.agent_id], timeout=1))[0]
    assert finished.status is AgentStatus.FAILED
    assert finished.result is not None and "end hook failed" in (finished.result.error or "")
