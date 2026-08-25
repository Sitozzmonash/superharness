"""Concurrent autonomous child-agent orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

from super_harness.agent import Agent
from super_harness.context import ContextFragment, ContextKind
from super_harness.exceptions import MultiAgentError, ToolError
from super_harness.hooks import HookContext, HookEvent, HookRegistry
from super_harness.models import MessageRole, ModelResponse, Usage
from super_harness.runtime.events import Event
from super_harness.runtime.thread import Thread
from super_harness.tools import Tool, ToolExecutor, tool


class AgentStatus(StrEnum):
    ROOT = "root"
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CLOSED = "closed"


class ContextInheritance(StrEnum):
    MINIMAL = "minimal"
    SELECTED = "selected"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class MultiAgentLimits:
    max_active_agents: int = 4
    max_total_agents: int = 16
    max_depth: int = 3
    total_token_budget: int = 100_000
    total_timeout: float = 3_600.0
    default_agent_timeout: float = 300.0
    max_result_chars: int = 20_000

    def __post_init__(self) -> None:
        values = (
            self.max_active_agents,
            self.max_total_agents,
            self.max_depth,
            self.total_token_budget,
            self.max_result_chars,
        )
        if any(value < 1 for value in values):
            raise ValueError("multi-agent count, depth, and token limits must be positive")
        if self.total_timeout <= 0 or self.default_agent_timeout <= 0:
            raise ValueError("multi-agent timeouts must be positive")


@dataclass(frozen=True, slots=True)
class SpawnRequest:
    task: str
    role: str
    parent_agent_id: str
    depth: int
    root_thread_id: str
    instructions: str | None = None
    inherited_context: tuple[ContextFragment, ...] = ()
    timeout: float = 300.0
    token_budget: int | None = None


AgentFactory = Callable[[SpawnRequest], Agent]


@dataclass(frozen=True, slots=True)
class AgentResult:
    agent_id: str
    status: AgentStatus
    text: str = ""
    artifacts: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    child_trace_ids: tuple[str, ...] = ()


def _payload() -> Mapping[str, Any]:
    return {}


def _strings() -> list[str]:
    return []


@dataclass(frozen=True, slots=True)
class AgentEvent:
    sequence: int
    type: str
    agent_id: str
    parent_agent_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: Mapping[str, Any] = field(default_factory=_payload)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class AgentSnapshot:
    agent_id: str
    parent_agent_id: str | None
    root_thread_id: str
    thread_id: str
    role: str
    task: str
    status: AgentStatus
    depth: int
    provider: str
    timeout: float
    token_budget: int | None
    created_at: datetime
    completed_at: datetime | None
    child_agent_ids: tuple[str, ...]
    queued_messages: tuple[str, ...]
    result: AgentResult | None
    turn_count: int


@dataclass(slots=True)
class _ManagedAgent:
    agent_id: str
    parent_agent_id: str | None
    root_thread_id: str
    role: str
    task: str
    depth: int
    agent: Agent
    thread: Thread
    timeout: float
    token_budget: int | None
    status: AgentStatus = AgentStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    child_agent_ids: list[str] = field(default_factory=_strings)
    queued_messages: list[str] = field(default_factory=_strings)
    result: AgentResult | None = None
    task_handle: asyncio.Task[None] | None = None
    interrupt_requested: bool = False

    def snapshot(self) -> AgentSnapshot:
        return AgentSnapshot(
            self.agent_id,
            self.parent_agent_id,
            self.root_thread_id,
            self.thread.thread_id,
            self.role,
            self.task,
            self.status,
            self.depth,
            self.agent.provider.name,
            self.timeout,
            self.token_budget,
            self.created_at,
            self.completed_at,
            tuple(self.child_agent_ids),
            tuple(self.queued_messages),
            self.result,
            len(self.thread.turns),
        )


class AgentManager:
    """Manage a bounded concurrent tree of independently configured Agents."""

    def __init__(
        self,
        root_agent: Agent,
        factory: AgentFactory,
        *,
        limits: MultiAgentLimits | None = None,
        hooks: HookRegistry | None = None,
        include_child_deltas: bool = False,
        expose_tools: bool = True,
    ) -> None:
        self.factory = factory
        self.limits = limits or MultiAgentLimits()
        self.hooks = hooks
        self.include_child_deltas = include_child_deltas
        self.expose_tools = expose_tools
        self.created_at = datetime.now(UTC)
        self._sequence = 0
        self._events: list[AgentEvent] = []
        self._event_condition = asyncio.Condition()
        self._completion_condition = asyncio.Condition()
        self._tokens_used = 0
        self.root_agent_id = str(uuid4())
        if expose_tools:
            self._attach_tools(root_agent, self.root_agent_id)
        root_thread = root_agent.thread()
        self.root_thread_id = root_thread.thread_id
        self._agents: dict[str, _ManagedAgent] = {
            self.root_agent_id: _ManagedAgent(
                self.root_agent_id,
                None,
                self.root_thread_id,
                "root",
                "root",
                0,
                root_agent,
                root_thread,
                self.limits.total_timeout,
                self.limits.total_token_budget,
                AgentStatus.ROOT,
            )
        }

    async def spawn_agent(
        self,
        parent_agent_id: str,
        task: str,
        *,
        role: str = "worker",
        instructions: str | None = None,
        inheritance: ContextInheritance = ContextInheritance.MINIMAL,
        selected_sources: Sequence[str] = (),
        timeout: float | None = None,
        token_budget: int | None = None,
    ) -> AgentSnapshot:
        parent = self._get(parent_agent_id)
        if not task.strip() or not role.strip():
            raise MultiAgentError("child task and role must be non-empty")
        depth = parent.depth + 1
        if depth > self.limits.max_depth:
            raise MultiAgentError("multi-agent depth limit exceeded")
        children = len(self._agents) - 1
        if children >= self.limits.max_total_agents:
            raise MultiAgentError("multi-agent total agent limit exceeded")
        if self._active_count() >= self.limits.max_active_agents:
            raise MultiAgentError("multi-agent active agent limit exceeded")
        self._check_global_budget()
        child_timeout = timeout or self.limits.default_agent_timeout
        if child_timeout <= 0:
            raise MultiAgentError("child timeout must be positive")
        if token_budget is not None and token_budget < 1:
            raise MultiAgentError("child token budget must be positive")
        context = self._inherit(parent, inheritance, selected_sources)
        request = SpawnRequest(
            task.strip(),
            role.strip(),
            parent_agent_id,
            depth,
            self.root_thread_id,
            instructions,
            context,
            child_timeout,
            token_budget,
        )
        try:
            agent = self.factory(request)
        except Exception as exc:
            raise MultiAgentError("child Agent factory failed") from exc
        agent_id = str(uuid4())
        if self.expose_tools:
            self._attach_tools(agent, agent_id)
        child = _ManagedAgent(
            agent_id,
            parent_agent_id,
            self.root_thread_id,
            role.strip(),
            task.strip(),
            depth,
            agent,
            agent.thread(),
            child_timeout,
            token_budget,
        )
        self._agents[agent_id] = child
        parent.child_agent_ids.append(agent_id)
        try:
            await self._emit("agent.spawned", child, {"role": child.role, "depth": depth})
            if self.hooks is not None:
                await self.hooks.dispatch(
                    HookContext(
                        HookEvent.SUBAGENT_START,
                        {"agent_id": agent_id, "task": child.task, "role": child.role},
                        self.root_thread_id,
                    )
                )
        except Exception as exc:
            parent.child_agent_ids.remove(agent_id)
            del self._agents[agent_id]
            raise MultiAgentError("subagent start hook failed") from exc
        child.task_handle = asyncio.create_task(self._run(child, child.task))
        return child.snapshot()

    async def send_input(self, agent_id: str, message: str) -> AgentSnapshot:
        child = self._child(agent_id)
        if not message.strip():
            raise MultiAgentError("agent input must be non-empty")
        if child.status is AgentStatus.RUNNING and child.thread.active_turn_id is not None:
            child.thread.queue_steering(child.thread.active_turn_id, message.strip())
        elif child.status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.INTERRUPTED,
            AgentStatus.CANCELLED,
            AgentStatus.CLOSED,
        }:
            child.queued_messages.append(message.strip())
        else:
            child.queued_messages.append(message.strip())
        await self._emit("agent.message", child, {"message": message.strip()})
        return child.snapshot()

    async def resume_agent(self, agent_id: str, message: str | None = None) -> AgentSnapshot:
        child = self._child(agent_id)
        if child.status in {AgentStatus.RUNNING, AgentStatus.PENDING}:
            raise MultiAgentError("cannot resume an active agent")
        if self._active_count() >= self.limits.max_active_agents:
            raise MultiAgentError("multi-agent active agent limit exceeded")
        self._check_global_budget()
        if message is not None:
            if not message.strip():
                raise MultiAgentError("resume input must be non-empty")
            child.queued_messages.append(message.strip())
        if not child.queued_messages:
            raise MultiAgentError("resume requires queued or explicit input")
        prompt = "\n\n".join(child.queued_messages)
        child.queued_messages.clear()
        child.interrupt_requested = False
        child.completed_at = None
        child.result = None
        child.status = AgentStatus.PENDING
        await self._emit("agent.resumed", child, {"message": prompt})
        child.task_handle = asyncio.create_task(self._run(child, prompt))
        return child.snapshot()

    async def wait(
        self,
        agent_ids: Sequence[str] | None = None,
        *,
        timeout: float | None = None,
    ) -> tuple[AgentSnapshot, ...]:
        targets = tuple(agent_ids or self._child_ids())
        if not targets:
            return ()
        for agent_id in targets:
            self._child(agent_id)

        def ready() -> bool:
            return any(self._get(agent_id).status not in _ACTIVE for agent_id in targets)

        if not ready():
            try:
                async with self._completion_condition:
                    await asyncio.wait_for(self._completion_condition.wait_for(ready), timeout)
            except TimeoutError:
                pass
        return tuple(self._get(agent_id).snapshot() for agent_id in targets)

    async def wait_all(
        self, agent_ids: Sequence[str] | None = None, *, timeout: float | None = None
    ) -> tuple[AgentSnapshot, ...]:
        targets = tuple(agent_ids or self._child_ids())
        if not targets:
            return ()
        for agent_id in targets:
            self._child(agent_id)

        def ready() -> bool:
            return all(self._get(agent_id).status not in _ACTIVE for agent_id in targets)

        if not ready():
            try:
                async with self._completion_condition:
                    await asyncio.wait_for(self._completion_condition.wait_for(ready), timeout)
            except TimeoutError:
                pass
        return tuple(self._get(agent_id).snapshot() for agent_id in targets)

    async def interrupt_agent(self, agent_id: str) -> AgentSnapshot:
        child = self._child(agent_id)
        if child.task_handle is None or child.task_handle.done():
            raise MultiAgentError("cannot interrupt an inactive agent")
        child.interrupt_requested = True
        child.task_handle.cancel()
        await _await_cancelled(child.task_handle)
        return child.snapshot()

    async def cancel(self, agent_id: str | None = None) -> None:
        target = self._get(agent_id or self.root_agent_id)
        ids = self._subtree(target.agent_id)
        for item_id in reversed(ids):
            item = self._get(item_id)
            if item.task_handle is not None and not item.task_handle.done():
                item.task_handle.cancel()
        await asyncio.gather(
            *(
                item.task_handle
                for item_id in ids
                if (item := self._get(item_id)).task_handle is not None
            ),
            return_exceptions=True,
        )

    async def close_agent(self, agent_id: str) -> AgentSnapshot:
        child = self._child(agent_id)
        await self.cancel(agent_id)
        for item_id in self._subtree(agent_id):
            item = self._get(item_id)
            item.status = AgentStatus.CLOSED
            item.completed_at = datetime.now(UTC)
            await item.thread.aclose()
            await self._emit("agent.closed", item)
        return child.snapshot()

    async def aclose(self) -> None:
        await self.cancel()
        for item in self._agents.values():
            await item.thread.aclose()
            await item.agent.aclose()

    def list_agents(self, *, parent_agent_id: str | None = None) -> tuple[AgentSnapshot, ...]:
        return tuple(
            item.snapshot()
            for item in self._agents.values()
            if parent_agent_id is None or item.parent_agent_id == parent_agent_id
        )

    def get(self, agent_id: str) -> AgentSnapshot:
        return self._get(agent_id).snapshot()

    def thread(self, agent_id: str) -> Thread:
        return self._get(agent_id).thread

    def results(self, agent_ids: Sequence[str] | None = None) -> tuple[AgentResult, ...]:
        targets = agent_ids or self._child_ids()
        return tuple(
            result
            for agent_id in targets
            if (result := self._child(agent_id).result) is not None
        )

    def event_history(self, *, after_sequence: int = 0) -> tuple[AgentEvent, ...]:
        return tuple(event for event in self._events if event.sequence > after_sequence)

    @property
    def tokens_used(self) -> int:
        return self._tokens_used

    def collaboration_tools(self, parent_agent_id: str) -> tuple[Tool, ...]:
        @tool(name="spawn_agent", source="multi_agent", risk="runtime")
        async def spawn_agent_tool(
            task: str,
            role: str = "worker",
            instructions: str | None = None,
            inheritance: str = "minimal",
            selected_sources: list[str] | None = None,
            timeout: float | None = None,
            token_budget: int | None = None,
        ) -> AgentSnapshot:
            """Spawn a bounded child Agent and start its task concurrently."""

            try:
                policy = ContextInheritance(inheritance)
            except ValueError as exc:
                raise MultiAgentError("invalid context inheritance policy") from exc
            return await self.spawn_agent(
                parent_agent_id,
                task,
                role=role,
                instructions=instructions,
                inheritance=policy,
                selected_sources=selected_sources or (),
                timeout=timeout,
                token_budget=token_budget,
            )

        @tool(name="send_input", source="multi_agent", risk="runtime")
        async def send_input_tool(agent_id: str, message: str) -> AgentSnapshot:
            """Send steering or queue a follow-up input for a child Agent."""

            return await self.send_input(agent_id, message)

        @tool(name="wait_agent", source="multi_agent", risk="runtime")
        async def wait_agent_tool(
            agent_ids: list[str] | None = None, timeout: float | None = 30.0
        ) -> list[dict[str, Any]]:
            """Wait until at least one selected child reaches a terminal state."""

            snapshots = await self.wait(agent_ids, timeout=timeout)
            return [asdict(snapshot) for snapshot in snapshots]

        @tool(name="resume_agent", source="multi_agent", risk="runtime")
        async def resume_agent_tool(agent_id: str, message: str | None = None) -> AgentSnapshot:
            """Resume an inactive child with queued or explicit input."""

            return await self.resume_agent(agent_id, message)

        @tool(name="interrupt_agent", source="multi_agent", risk="runtime")
        async def interrupt_agent_tool(agent_id: str) -> AgentSnapshot:
            """Interrupt one active child without cancelling its parent."""

            return await self.interrupt_agent(agent_id)

        @tool(name="close_agent", source="multi_agent", risk="runtime")
        async def close_agent_tool(agent_id: str) -> AgentSnapshot:
            """Close a child subtree while retaining resumable state."""

            return await self.close_agent(agent_id)

        return (
            spawn_agent_tool,
            send_input_tool,
            wait_agent_tool,
            resume_agent_tool,
            interrupt_agent_tool,
            close_agent_tool,
        )

    async def events(self, *, after_sequence: int = 0) -> AsyncIterator[AgentEvent]:
        cursor = max(after_sequence, 0)
        while True:
            available = [event for event in self._events if event.sequence > cursor]
            if available:
                for event in available:
                    cursor = event.sequence
                    yield event
                continue
            async with self._event_condition:
                await self._event_condition.wait()

    async def _run(self, child: _ManagedAgent, prompt: str) -> None:
        child.status = AgentStatus.RUNNING
        await self._emit("agent.started", child)
        response: ModelResponse | None = None
        usage = Usage()
        try:
            async with asyncio.timeout(min(child.timeout, self._remaining_seconds())):
                async for event in child.thread.astream(prompt):
                    await self._emit_thread_event(child, event)
                    if event.type == "model.completed":
                        candidate_usage = event.payload.get("usage")
                        if isinstance(candidate_usage, Usage):
                            usage = Usage(
                                usage.input_tokens + candidate_usage.input_tokens,
                                usage.output_tokens + candidate_usage.output_tokens,
                                usage.total_tokens + candidate_usage.total_tokens,
                            )
                    if event.type == "turn.completed":
                        candidate = event.payload.get("response")
                        if isinstance(candidate, ModelResponse):
                            response = candidate
            if response is None:
                raise MultiAgentError("child turn completed without a response")
            response = replace(response, usage=usage)
            self._tokens_used += usage.total_tokens
            status = AgentStatus.COMPLETED
            if child.token_budget is not None and usage.total_tokens > child.token_budget:
                status = AgentStatus.BUDGET_EXHAUSTED
            if self._tokens_used > self.limits.total_token_budget:
                status = AgentStatus.BUDGET_EXHAUSTED
            child.status = status
            child.result = _result(
                child,
                response,
                status,
                self.limits.max_result_chars,
                tuple(self._get(item).thread.thread_id for item in child.child_agent_ids),
            )
            child.completed_at = datetime.now(UTC)
            await self._emit("agent.completed", child, {"result": child.result})
        except asyncio.CancelledError:
            child.status = (
                AgentStatus.INTERRUPTED if child.interrupt_requested else AgentStatus.CANCELLED
            )
            child.completed_at = datetime.now(UTC)
            child.result = AgentResult(child.agent_id, child.status, error=child.status.value)
            await self._emit(f"agent.{child.status.value}", child)
        except TimeoutError:
            child.status = AgentStatus.FAILED
            child.completed_at = datetime.now(UTC)
            child.result = AgentResult(child.agent_id, child.status, error="agent timed out")
            await self._emit("agent.failed", child, {"error": "agent timed out"})
        except Exception as exc:
            child.status = AgentStatus.FAILED
            child.completed_at = datetime.now(UTC)
            child.result = AgentResult(
                child.agent_id,
                child.status,
                error=f"{type(exc).__name__}: {exc}",
            )
            await self._emit("agent.failed", child, {"error_type": type(exc).__name__})
        finally:
            try:
                if self.hooks is not None:
                    await self.hooks.dispatch(
                        HookContext(
                            HookEvent.SUBAGENT_END,
                            {"agent_id": child.agent_id, "result": child.result},
                            self.root_thread_id,
                        )
                    )
            except Exception as exc:
                child.status = AgentStatus.FAILED
                child.completed_at = datetime.now(UTC)
                child.result = AgentResult(
                    child.agent_id,
                    AgentStatus.FAILED,
                    error=f"subagent end hook failed: {type(exc).__name__}",
                )
                await self._emit("agent.failed", child, {"error_type": type(exc).__name__})
            finally:
                async with self._completion_condition:
                    self._completion_condition.notify_all()

    async def _emit_thread_event(self, child: _ManagedAgent, event: Event) -> None:
        if not self.include_child_deltas and event.type in {
            "model.text.delta",
            "model.tool_call.delta",
        }:
            return
        await self._emit(
            "agent.event",
            child,
            {"event_type": event.type, "turn_id": event.turn_id, "payload": event.payload},
        )

    async def _emit(
        self, type_name: str, child: _ManagedAgent, payload: Mapping[str, Any] | None = None
    ) -> None:
        self._sequence += 1
        event = AgentEvent(
            self._sequence,
            type_name,
            child.agent_id,
            child.parent_agent_id,
            payload=payload or {},
        )
        self._events.append(event)
        async with self._event_condition:
            self._event_condition.notify_all()

    def _inherit(
        self,
        parent: _ManagedAgent,
        inheritance: ContextInheritance,
        selected_sources: Sequence[str],
    ) -> tuple[ContextFragment, ...]:
        fragments = tuple(parent.thread.context.fragments)
        if inheritance is ContextInheritance.MINIMAL:
            return ()
        if inheritance is ContextInheritance.SELECTED:
            selected = set(selected_sources)
            if not selected:
                raise MultiAgentError("selected context inheritance requires sources")
            return tuple(item for item in fragments if item.source in selected)
        history = "\n".join(
            f"{message.role.value}: {message.content}" for message in parent.thread.messages
        )
        if history:
            fragments = (
                *fragments,
                ContextFragment(
                    ContextKind.MEMORY,
                    history,
                    f"agent:{parent.agent_id}:history",
                    MessageRole.USER,
                ),
            )
        return fragments

    def _active_count(self) -> int:
        return sum(item.status in _ACTIVE for item in self._agents.values())

    def _attach_tools(self, agent: Agent, agent_id: str) -> None:
        try:
            for item in self.collaboration_tools(agent_id):
                agent.tool_registry.register(item)
        except ToolError as exc:
            raise MultiAgentError("Agent has a conflicting collaboration tool") from exc
        if agent.tool_executor is None:
            agent.tool_executor = ToolExecutor(agent.tool_registry, hooks=agent.hooks)

    def _check_global_budget(self) -> None:
        if self._tokens_used >= self.limits.total_token_budget:
            raise MultiAgentError("multi-agent token budget exhausted")
        if self._remaining_seconds() <= 0:
            raise MultiAgentError("multi-agent time budget exhausted")

    def _remaining_seconds(self) -> float:
        elapsed = (datetime.now(UTC) - self.created_at).total_seconds()
        return self.limits.total_timeout - elapsed

    def _child_ids(self) -> tuple[str, ...]:
        return tuple(agent_id for agent_id in self._agents if agent_id != self.root_agent_id)

    def _subtree(self, agent_id: str) -> list[str]:
        result = [agent_id]
        for child_id in self._get(agent_id).child_agent_ids:
            result.extend(self._subtree(child_id))
        return result

    def _get(self, agent_id: str) -> _ManagedAgent:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise MultiAgentError(f"unknown agent {agent_id!r}") from exc

    def _child(self, agent_id: str) -> _ManagedAgent:
        child = self._get(agent_id)
        if child.parent_agent_id is None:
            raise MultiAgentError("operation requires a child agent")
        return child


_ACTIVE = frozenset({AgentStatus.PENDING, AgentStatus.RUNNING, AgentStatus.WAITING})


def _result(
    child: _ManagedAgent,
    response: ModelResponse,
    status: AgentStatus,
    max_result_chars: int,
    child_trace_ids: tuple[str, ...],
) -> AgentResult:
    artifacts: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    if response.output_json is not None:
        raw_artifacts = response.output_json.get("artifacts")
        raw_references = response.output_json.get("references")
        if isinstance(raw_artifacts, tuple):
            artifacts = tuple(str(item) for item in cast(tuple[Any, ...], raw_artifacts))
        if isinstance(raw_references, tuple):
            references = tuple(str(item) for item in cast(tuple[Any, ...], raw_references))
    return AgentResult(
        child.agent_id,
        status,
        response.text[:max_result_chars],
        artifacts,
        references,
        usage=response.usage,
        child_trace_ids=child_trace_ids,
    )


async def _await_cancelled(task: asyncio.Task[None]) -> None:
    with suppress(asyncio.CancelledError):
        await task
