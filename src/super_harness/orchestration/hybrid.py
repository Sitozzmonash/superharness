"""Adapters that compose autonomous Agents and deterministic workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from super_harness.exceptions import WorkflowError

from .autonomous import AgentEvent, AgentManager, AgentStatus, ContextInheritance
from .workflow import (
    JSONWorkflowStore,
    Node,
    NodeKind,
    NodeOutput,
    Workflow,
    WorkflowContext,
    WorkflowEngine,
    WorkflowRun,
    WorkflowStatus,
)

PromptBuilder = str | Callable[[WorkflowContext], str]
InputBuilder = Callable[[WorkflowContext], Any]
StateBuilder = Callable[[WorkflowContext], Mapping[str, Any]]


def _string_map() -> dict[str, str]:
    return {}


def _input(context: WorkflowContext) -> Any:
    return context.workflow_input


@dataclass(slots=True)
class AutonomousAgentNode:
    """Workflow handler that runs one autonomous Agent subtree."""

    manager: AgentManager
    task: PromptBuilder
    role: str = "worker"
    parent_agent_id: str | None = None
    instructions: str | None = None
    inheritance: ContextInheritance = ContextInheritance.MINIMAL
    selected_sources: tuple[str, ...] = ()
    timeout: float | None = None
    token_budget: int | None = None
    _agent_ids: dict[str, str] = field(default_factory=_string_map, init=False, repr=False)

    async def __call__(self, context: WorkflowContext) -> NodeOutput:
        task = self.task(context) if callable(self.task) else self.task
        if not task.strip():
            raise WorkflowError("autonomous agent node produced an empty task")
        cursor = max(
            (event.sequence for event in self.manager.event_history()),
            default=0,
        )
        child = await self.manager.spawn_agent(
            self.parent_agent_id or self.manager.root_agent_id,
            task,
            role=self.role,
            instructions=self.instructions,
            inheritance=self.inheritance,
            selected_sources=self.selected_sources,
            timeout=self.timeout,
            token_budget=self.token_budget,
        )
        self._agent_ids[context.run_id] = child.agent_id
        try:
            finished = (await self.manager.wait_all([child.agent_id], timeout=self.timeout))[0]
            descendants = _descendant_ids(self.manager, child.agent_id)
            descendant_snapshots = ()
            if descendants:
                descendant_snapshots = await self.manager.wait_all(
                    descendants,
                    timeout=self.timeout,
                )
            snapshots = (finished, *descendant_snapshots)
            active = {
                AgentStatus.PENDING,
                AgentStatus.RUNNING,
                AgentStatus.WAITING,
            }
            if any(snapshot.status in active for snapshot in snapshots):
                await self.manager.cancel(child.agent_id)
                finished = self.manager.get(child.agent_id)
            await _forward_agent_events(
                context,
                child.agent_id,
                self.manager.event_history(after_sequence=cursor),
            )
            result = finished.result
            if finished.status is not AgentStatus.COMPLETED or result is None:
                message = (
                    result.error if result is not None else f"agent ended as {finished.status}"
                )
                raise WorkflowError(f"autonomous agent node failed: {message}")
            failed_descendant = next(
                (
                    snapshot
                    for snapshot in descendant_snapshots
                    if snapshot.status is not AgentStatus.COMPLETED
                ),
                None,
            )
            if failed_descendant is not None:
                raise WorkflowError(
                    "autonomous agent descendant failed: "
                    f"{failed_descendant.agent_id}={failed_descendant.status}"
                )
            return NodeOutput(
                result.text,
                {
                    f"hybrid.{context.node_id}.agent_id": child.agent_id,
                    f"hybrid.{context.node_id}.thread_id": finished.thread_id,
                    f"hybrid.{context.node_id}.tokens": result.usage.total_tokens,
                },
            )
        except asyncio.CancelledError:
            await self.manager.cancel(child.agent_id)
            await _forward_agent_events(
                context,
                child.agent_id,
                self.manager.event_history(after_sequence=cursor),
            )
            raise
        finally:
            self._agent_ids.pop(context.run_id, None)

    async def cancel(self, run_id: str) -> bool:
        agent_id = self._agent_ids.get(run_id)
        if agent_id is None:
            return False
        await self.manager.cancel(agent_id)
        return True


@dataclass(slots=True)
class SubworkflowNode:
    """Workflow handler that executes or resumes a nested workflow."""

    workflow: Workflow
    engine: WorkflowEngine
    input_builder: InputBuilder = _input
    state_builder: StateBuilder | None = None
    _active_runs: dict[str, str] = field(default_factory=_string_map, init=False, repr=False)

    async def __call__(self, context: WorkflowContext) -> NodeOutput:
        child_run_id = _child_run_id(context.run_id, context.node_id)
        self._active_runs[context.run_id] = child_run_id
        checkpoint = _load_if_present(self.engine.store, child_run_id)
        event_cursor = len(checkpoint.events) if checkpoint is not None else 0
        try:
            if checkpoint is not None:
                child = await self.engine.resume(self.workflow, checkpoint)
            else:
                initial_state = self.state_builder(context) if self.state_builder else None
                child = await self.engine.run(
                    self.workflow,
                    self.input_builder(context),
                    state=initial_state,
                    run_id=child_run_id,
                )
            await _forward_subworkflow_events(context, child, after_sequence=event_cursor)
            if child.status is not WorkflowStatus.COMPLETED:
                raise WorkflowError(f"subworkflow failed: {child.error or child.status.value}")
            return NodeOutput(
                child.output,
                {
                    f"hybrid.{context.node_id}.workflow_id": child.workflow_id,
                    f"hybrid.{context.node_id}.run_id": child.run_id,
                },
            )
        except asyncio.CancelledError:
            await self.engine.cancel(child_run_id)
            checkpoint = _load_if_present(self.engine.store, child_run_id)
            if checkpoint is not None:
                await _forward_subworkflow_events(context, checkpoint)
            raise
        finally:
            self._active_runs.pop(context.run_id, None)

    async def cancel(self, run_id: str) -> bool:
        child_run_id = self._active_runs.get(run_id)
        return False if child_run_id is None else await self.engine.cancel(child_run_id)


def agent_node(
    node_id: str,
    manager: AgentManager,
    task: PromptBuilder,
    *,
    role: str = "worker",
    parent_agent_id: str | None = None,
    instructions: str | None = None,
    inheritance: ContextInheritance = ContextInheritance.MINIMAL,
    selected_sources: Sequence[str] = (),
    timeout: float | None = None,
    token_budget: int | None = None,
) -> Node:
    handler = AutonomousAgentNode(
        manager,
        task,
        role,
        parent_agent_id,
        instructions,
        inheritance,
        tuple(selected_sources),
        timeout,
        token_budget,
    )
    return Node(node_id, handler, NodeKind.AGENT, timeout=timeout)


def subworkflow_node(
    node_id: str,
    workflow: Workflow,
    *,
    engine: WorkflowEngine | None = None,
    input_builder: InputBuilder = _input,
    state_builder: StateBuilder | None = None,
) -> Node:
    handler = SubworkflowNode(
        workflow,
        engine or WorkflowEngine(),
        input_builder,
        state_builder,
    )
    return Node(node_id, handler, NodeKind.SUBWORKFLOW)


def _descendant_ids(manager: AgentManager, agent_id: str) -> list[str]:
    descendants: list[str] = []
    pending = [agent_id]
    while pending:
        parent = pending.pop()
        children = manager.list_agents(parent_agent_id=parent)
        for child in children:
            descendants.append(child.agent_id)
            pending.append(child.agent_id)
    return descendants


async def _forward_agent_events(
    context: WorkflowContext,
    root_agent_id: str,
    events: Sequence[AgentEvent],
) -> None:
    relevant = {root_agent_id}
    for event in events:
        if event.parent_agent_id in relevant:
            relevant.add(event.agent_id)
        if event.agent_id not in relevant:
            continue
        await context.emit(
            event.type,
            {
                "source": "autonomous_agent",
                "agent_sequence": event.sequence,
                "agent_id": event.agent_id,
                "parent_agent_id": event.parent_agent_id,
            },
        )


async def _forward_subworkflow_events(
    context: WorkflowContext,
    run: WorkflowRun,
    *,
    after_sequence: int = 0,
) -> None:
    for event in run.events:
        if event.sequence <= after_sequence:
            continue
        await context.emit(
            f"subworkflow.{event.type}",
            {
                "source": "subworkflow",
                "child_workflow_id": run.workflow_id,
                "child_run_id": run.run_id,
                "child_sequence": event.sequence,
                "child_node_id": event.node_id,
            },
        )


def _child_run_id(parent_run_id: str, node_id: str) -> str:
    safe_node_id = "".join(
        character if character.isalnum() or character in "-_" else "-"
        for character in node_id
    )
    return f"{parent_run_id}-{safe_node_id}"


def _load_if_present(
    store: JSONWorkflowStore | None,
    run_id: str,
) -> WorkflowRun | None:
    if store is None:
        return None
    try:
        return store.load(run_id)
    except FileNotFoundError:
        return None
