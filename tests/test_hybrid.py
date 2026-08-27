from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from super_harness import (
    Agent,
    AgentManager,
    AgentStatus,
    Edge,
    JSONWorkflowStore,
    Node,
    NodeOutput,
    SpawnRequest,
    Workflow,
    WorkflowContext,
    WorkflowEngine,
    WorkflowStatus,
    agent_node,
    subworkflow_node,
)
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
    Usage,
)


class StaticProvider:
    name = "hybrid-static"
    capabilities = ModelCapabilities()

    def __init__(
        self,
        *,
        text: str = "agent-result",
        started: asyncio.Event | None = None,
        block: bool = False,
        fail: bool = False,
    ) -> None:
        self.text = text
        self.started = started
        self.block = block
        self.fail = fail

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if self.started is not None:
            self.started.set()
        if self.block:
            await asyncio.Event().wait()
        if self.fail:
            raise RuntimeError("agent provider failed")
        prompt = request.messages[-1].content
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(f"{self.text}:{prompt}", usage=Usage(1, 2, 3)),
        )

    async def aclose(self) -> None:
        return None


class TeamLeadProvider:
    name = "hybrid-lead"
    capabilities = ModelCapabilities()

    def __init__(self) -> None:
        self.step = 0
        self.children: list[str] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.step += 1
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if self.step in {1, 2}:
            if self.step == 2:
                self.children.append(str(json.loads(request.messages[-1].content)["agent_id"]))
            index = self.step
            call = ToolCall(
                f"spawn-{index}",
                "spawn_agent",
                {"task": f"specialist-{index}", "role": "specialist"},
                json.dumps({"task": f"specialist-{index}", "role": "specialist"}),
            )
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(tool_calls=(call,)),
            )
            return
        if self.step == 3:
            self.children.append(str(json.loads(request.messages[-1].content)["agent_id"]))
            arguments = {"agent_ids": self.children, "timeout": 2.0}
            call = ToolCall("wait", "wait_agent", arguments, json.dumps(arguments))
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(tool_calls=(call,)),
            )
            return
        results = json.loads(request.messages[-1].content)
        assert all(item["status"] == "completed" for item in results)
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse("team-aggregate", usage=Usage(2, 3, 5)),
        )

    async def aclose(self) -> None:
        return None


def _manager(provider_factory: object | None = None) -> AgentManager:
    def factory(request: SpawnRequest) -> Agent:
        if callable(provider_factory):
            provider = provider_factory(request)
            assert isinstance(provider, (StaticProvider, TeamLeadProvider))
        else:
            provider = StaticProvider(text=request.role)
        return Agent(provider)

    return AgentManager(Agent(StaticProvider()), factory)


@pytest.mark.asyncio
async def test_autonomous_agent_node_runs_inside_sequence_and_bridges_events() -> None:
    manager = _manager()
    workflow = Workflow(
        "hybrid-agent",
        [
            Node("prepare", lambda context: str(context.workflow_input).upper()),
            agent_node(
                "research",
                manager,
                lambda context: f"research {context.results['prepare'].value}",
                role="researcher",
            ),
            Node("finish", lambda context: f"final:{context.results['research'].value}"),
        ],
        [Edge("prepare", "research"), Edge("research", "finish")],
    )

    run = await WorkflowEngine().run(workflow, "topic")

    assert run.status == WorkflowStatus.COMPLETED
    assert run.output == "final:researcher:research TOPIC"
    assert str(run.state.values["hybrid.research.agent_id"])
    bridged = [event for event in run.events if event.payload.get("source") == "autonomous_agent"]
    assert {event.type for event in bridged} >= {
        "agent.spawned",
        "agent.started",
        "agent.completed",
    }
    assert all(event.node_id == "research" for event in bridged)


@pytest.mark.asyncio
async def test_subworkflow_node_returns_output_state_and_correlated_events(
    tmp_path: Path,
) -> None:
    child = Workflow(
        "child",
        [
            Node("double", lambda context: int(context.workflow_input) * 2),
            Node("label", lambda context: f"value={context.results['double'].value}"),
        ],
        [Edge("double", "label")],
    )
    child_engine = WorkflowEngine(store=JSONWorkflowStore(tmp_path / "child"))
    parent = Workflow(
        "parent",
        [
            subworkflow_node("nested", child, engine=child_engine),
            Node("finish", lambda context: f"parent:{context.results['nested'].value}"),
        ],
        [Edge("nested", "finish")],
    )

    run = await WorkflowEngine().run(parent, 21, run_id="parent-run")

    assert run.output == "parent:value=42"
    assert run.state.values["hybrid.nested.run_id"] == "parent-run-nested"
    child_events = [event for event in run.events if event.payload.get("source") == "subworkflow"]
    assert child_events
    assert all(event.node_id == "nested" for event in child_events)
    assert child_engine.store is not None
    assert child_engine.store.load("parent-run-nested").status == WorkflowStatus.COMPLETED


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workflow_agent_autonomously_invokes_specialist_team() -> None:
    lead_provider = TeamLeadProvider()

    def providers(request: SpawnRequest) -> StaticProvider | TeamLeadProvider:
        return lead_provider if request.role == "lead" else StaticProvider(text=request.role)

    manager = _manager(providers)
    workflow = Workflow(
        "specialist-team",
        [agent_node("team", manager, "coordinate specialists", role="lead", timeout=2)],
    )

    run = await WorkflowEngine().run(workflow)

    assert run.status == WorkflowStatus.COMPLETED
    assert run.output == "team-aggregate"
    lead = manager.list_agents(parent_agent_id=manager.root_agent_id)[0]
    specialists = manager.list_agents(parent_agent_id=lead.agent_id)
    assert len(specialists) == 2
    assert all(snapshot.status == AgentStatus.COMPLETED for snapshot in specialists)
    agent_ids = {
        event.payload.get("agent_id")
        for event in run.events
        if event.payload.get("source") == "autonomous_agent"
    }
    assert {lead.agent_id, *(item.agent_id for item in specialists)} <= agent_ids


@pytest.mark.asyncio
async def test_workflow_cancel_cascades_into_agent_subtree() -> None:
    started = asyncio.Event()

    def providers(_: SpawnRequest) -> StaticProvider:
        return StaticProvider(started=started, block=True)

    manager = _manager(providers)
    workflow = Workflow(
        "cancel-agent",
        [agent_node("agent", manager, "block", timeout=30)],
    )
    engine = WorkflowEngine()
    task = asyncio.create_task(engine.run(workflow, run_id="cancel-agent-run"))
    await started.wait()

    assert await engine.cancel("cancel-agent-run") is True
    run = await task

    assert run.status == WorkflowStatus.INTERRUPTED
    child = manager.list_agents(parent_agent_id=manager.root_agent_id)[0]
    assert child.status == AgentStatus.CANCELLED
    assert any(event.payload.get("source") == "autonomous_agent" for event in run.events)


@pytest.mark.asyncio
async def test_parent_cancel_interrupts_and_checkpoints_subworkflow(tmp_path: Path) -> None:
    started = asyncio.Event()

    async def slow(_: WorkflowContext) -> None:
        started.set()
        await asyncio.sleep(60)

    child_store = JSONWorkflowStore(tmp_path / "child")
    child_engine = WorkflowEngine(store=child_store)
    child = Workflow("slow-child", [Node("slow", slow)])
    parent = Workflow(
        "cancel-parent",
        [subworkflow_node("nested", child, engine=child_engine)],
    )
    parent_engine = WorkflowEngine(store=JSONWorkflowStore(tmp_path / "parent"))
    task = asyncio.create_task(parent_engine.run(parent, run_id="cancel-parent-run"))
    await started.wait()

    assert await parent_engine.cancel("cancel-parent-run") is True
    run = await task

    assert run.status == WorkflowStatus.INTERRUPTED
    child_run = child_store.load("cancel-parent-run-nested")
    assert child_run.status == WorkflowStatus.INTERRUPTED


@pytest.mark.asyncio
async def test_failed_subworkflow_resumes_stable_child_checkpoint(tmp_path: Path) -> None:
    first_calls = 0
    second_calls = 0
    fail = True

    def first(_: WorkflowContext) -> NodeOutput:
        nonlocal first_calls
        first_calls += 1
        return NodeOutput("stable", {"child_saved": True})

    def second(_: WorkflowContext) -> str:
        nonlocal second_calls
        second_calls += 1
        if fail:
            raise RuntimeError("retry later")
        return "recovered"

    child = Workflow(
        "resumable-child",
        [Node("first", first), Node("second", second)],
        [Edge("first", "second")],
    )
    child_engine = WorkflowEngine(store=JSONWorkflowStore(tmp_path / "child"))
    parent = Workflow(
        "resumable-parent",
        [subworkflow_node("nested", child, engine=child_engine)],
    )
    parent_store = JSONWorkflowStore(tmp_path / "parent")
    parent_engine = WorkflowEngine(store=parent_store)

    failed = await parent_engine.run(parent, run_id="resume-parent-run")
    fail = False
    resumed = await parent_engine.resume(parent, parent_store.load("resume-parent-run"))

    assert failed.status == WorkflowStatus.FAILED
    assert resumed.status == WorkflowStatus.COMPLETED
    assert resumed.output == "recovered"
    assert first_calls == 1
    assert second_calls == 2
    child_run = child_engine.store.load("resume-parent-run-nested") if child_engine.store else None
    assert child_run is not None and child_run.state.values == {"child_saved": True}
