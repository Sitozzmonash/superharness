"""Deterministic, resumable workflow orchestration."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4

from super_harness.exceptions import WorkflowError


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _values() -> dict[str, Any]:
    return {}


def _events() -> list[WorkflowEvent]:
    return []


class NodeKind(StrEnum):
    FUNCTION = "function"
    TOOL = "tool"
    AGENT = "agent"
    ROUTER = "router"
    SUBWORKFLOW = "subworkflow"
    TRANSFORM = "transform"
    GATE = "gate"


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry settings for an idempotent node invocation."""

    max_attempts: int = 1
    backoff_seconds: float = 0.0
    multiplier: float = 2.0
    max_backoff_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.backoff_seconds < 0 or self.max_backoff_seconds < 0:
            raise ValueError("retry backoff values cannot be negative")
        if self.multiplier < 1:
            raise ValueError("retry multiplier must be at least one")

    def delay(self, failed_attempt: int) -> float:
        delay = self.backoff_seconds * self.multiplier ** max(0, failed_attempt - 1)
        return min(delay, self.max_backoff_seconds)


@dataclass(frozen=True, slots=True)
class NodeOutput:
    """Optional structured output with atomic state updates and a route label."""

    value: Any = None
    updates: Mapping[str, Any] = field(default_factory=_values)
    route: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "updates", MappingProxyType(dict(self.updates)))


@dataclass(frozen=True, slots=True)
class WorkflowContext:
    workflow_id: str
    run_id: str
    node_id: str
    workflow_input: Any
    state: Mapping[str, Any]
    results: Mapping[str, NodeResult]
    attempt: int
    iteration: int


NodeHandler = Callable[[WorkflowContext], object]
EdgePredicate = Callable[[WorkflowContext, "NodeResult"], bool]
LoopPredicate = Callable[[WorkflowContext, Any], bool]
EventListener = Callable[["WorkflowEvent"], object]


@dataclass(frozen=True, slots=True)
class Node:
    node_id: str
    handler: NodeHandler
    kind: NodeKind = NodeKind.FUNCTION
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None
    idempotent: bool = False
    loop_until: LoopPredicate | None = None
    max_iterations: int = 1

    def __post_init__(self) -> None:
        if not self.node_id or not self.node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        if self.timeout is not None and self.timeout <= 0:
            raise ValueError("node timeout must be positive")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least one")
        if self.loop_until is None and self.max_iterations != 1:
            raise ValueError("max_iterations greater than one requires loop_until")
        if self.retry.max_attempts > 1 and not self.idempotent:
            raise ValueError("retried nodes must explicitly declare idempotent=True")


@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    route: str | None = None
    predicate: EdgePredicate | None = None

    def __post_init__(self) -> None:
        if not self.source or not self.target:
            raise ValueError("edge endpoints must be non-empty")
        if self.route is not None and self.predicate is not None:
            raise ValueError("an edge cannot declare both route and predicate")

    @property
    def conditional(self) -> bool:
        return self.route is not None or self.predicate is not None


@dataclass(slots=True)
class NodeResult:
    node_id: str
    status: NodeStatus = NodeStatus.PENDING
    value: Any = None
    route: str | None = None
    attempts: int = 0
    iterations: int = 0
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "value": self.value,
            "route": self.route,
            "attempts": self.attempts,
            "iterations": self.iterations,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NodeResult:
        return cls(
            node_id=str(value["node_id"]),
            status=NodeStatus(str(value["status"])),
            value=value.get("value"),
            route=cast(str | None, value.get("route")),
            attempts=int(value.get("attempts", 0)),
            iterations=int(value.get("iterations", 0)),
            error=cast(str | None, value.get("error")),
            started_at=_optional_datetime(value.get("started_at")),
            completed_at=_optional_datetime(value.get("completed_at")),
        )


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    sequence: int
    type: str
    workflow_id: str
    run_id: str
    node_id: str | None = None
    timestamp: datetime = field(default_factory=_utc_now)
    payload: Mapping[str, Any] = field(default_factory=_values)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "type": self.type,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "timestamp": self.timestamp.isoformat(),
            "payload": dict(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkflowEvent:
        return cls(
            sequence=int(value["sequence"]),
            type=str(value["type"]),
            workflow_id=str(value["workflow_id"]),
            run_id=str(value["run_id"]),
            node_id=cast(str | None, value.get("node_id")),
            timestamp=datetime.fromisoformat(str(value["timestamp"])),
            payload=cast(Mapping[str, Any], value.get("payload") or {}),
        )


@dataclass(slots=True)
class WorkflowState:
    values: dict[str, Any] = field(default_factory=_values)

    def update(self, values: Mapping[str, Any]) -> None:
        self.values.update(values)

    def snapshot(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(self.values))


@dataclass(slots=True)
class WorkflowRun:
    workflow_id: str
    run_id: str
    workflow_input: Any
    state: WorkflowState
    node_results: dict[str, NodeResult]
    status: WorkflowStatus = WorkflowStatus.PENDING
    events: list[WorkflowEvent] = field(default_factory=_events)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None
    error: str | None = None

    @property
    def output(self) -> Any:
        completed = [
            result
            for result in self.node_results.values()
            if result.status == NodeStatus.COMPLETED
        ]
        return completed[-1].value if completed else None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "schema_version": 1,
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "workflow_input": self.workflow_input,
            "state": dict(self.state.values),
            "node_results": {key: value.to_dict() for key, value in self.node_results.items()},
            "status": self.status.value,
            "events": [event.to_dict() for event in self.events],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }
        _assert_json_serializable(data)
        return data

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> WorkflowRun:
        if int(value.get("schema_version", 0)) != 1:
            raise WorkflowError("unsupported workflow checkpoint schema")
        raw_results = cast(Mapping[str, Mapping[str, Any]], value["node_results"])
        raw_events = cast(Sequence[Mapping[str, Any]], value.get("events") or ())
        return cls(
            workflow_id=str(value["workflow_id"]),
            run_id=str(value["run_id"]),
            workflow_input=value.get("workflow_input"),
            state=WorkflowState(dict(cast(Mapping[str, Any], value.get("state") or {}))),
            node_results={key: NodeResult.from_dict(item) for key, item in raw_results.items()},
            status=WorkflowStatus(str(value["status"])),
            events=[WorkflowEvent.from_dict(item) for item in raw_events],
            created_at=datetime.fromisoformat(str(value["created_at"])),
            updated_at=datetime.fromisoformat(str(value["updated_at"])),
            completed_at=_optional_datetime(value.get("completed_at")),
            error=cast(str | None, value.get("error")),
        )

    @classmethod
    def from_json(cls, value: str) -> WorkflowRun:
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise WorkflowError("workflow checkpoint must be a JSON object")
        return cls.from_dict(cast(Mapping[str, Any], parsed))


@dataclass(frozen=True, slots=True)
class Workflow:
    workflow_id: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...] = ()

    def __init__(
        self,
        workflow_id: str,
        nodes: Sequence[Node],
        edges: Sequence[Edge] = (),
    ) -> None:
        object.__setattr__(self, "workflow_id", workflow_id)
        object.__setattr__(self, "nodes", tuple(nodes))
        object.__setattr__(self, "edges", tuple(edges))
        self.validate()

    def validate(self) -> None:
        if not self.workflow_id or not self.workflow_id.strip():
            raise WorkflowError("workflow_id must be a non-empty string")
        if not self.nodes:
            raise WorkflowError("workflow must contain at least one node")
        identifiers = [node.node_id for node in self.nodes]
        if len(set(identifiers)) != len(identifiers):
            raise WorkflowError("workflow node IDs must be unique")
        known = set(identifiers)
        for edge in self.edges:
            if edge.source not in known or edge.target not in known:
                raise WorkflowError(
                    f"edge references unknown node: {edge.source!r} -> {edge.target!r}"
                )
            if edge.source == edge.target:
                raise WorkflowError("self cycles require an explicit loop node")
        indegree = dict.fromkeys(identifiers, 0)
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in identifiers}
        for edge in self.edges:
            indegree[edge.target] += 1
            outgoing[edge.source].append(edge.target)
        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        visited = 0
        while ready:
            node_id = ready.pop()
            visited += 1
            for target in outgoing[node_id]:
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target)
        if visited != len(identifiers):
            raise WorkflowError("unsupported graph cycle; use Node.loop_until with a strict limit")

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise WorkflowError(f"unknown workflow node: {node_id}")


class JSONWorkflowStore:
    """Atomic JSON checkpoint storage keyed by workflow run ID."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, run: WorkflowRun) -> Path:
        path = self._path(run.run_id)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(run.to_json(indent=2), encoding="utf-8")
        temporary.replace(path)
        return path

    def load(self, run_id: str) -> WorkflowRun:
        return WorkflowRun.from_json(self._path(run_id).read_text(encoding="utf-8"))

    def _path(self, run_id: str) -> Path:
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        if not run_id or any(character not in allowed for character in run_id):
            raise WorkflowError("invalid workflow run ID")
        return self.directory / f"{run_id}.json"


class WorkflowEngine:
    """Execute validated DAGs in dependency batches with stable checkpoints."""

    def __init__(
        self,
        *,
        max_concurrency: int = 8,
        store: JSONWorkflowStore | None = None,
        event_listener: EventListener | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.max_concurrency = max_concurrency
        self.store = store
        self.event_listener = event_listener
        self._cancel_requests: dict[str, asyncio.Event] = {}
        self._node_tasks: dict[str, set[asyncio.Task[None]]] = {}

    async def run(
        self,
        workflow: Workflow,
        workflow_input: Any = None,
        *,
        state: Mapping[str, Any] | None = None,
        run_id: str | None = None,
    ) -> WorkflowRun:
        workflow.validate()
        run = WorkflowRun(
            workflow_id=workflow.workflow_id,
            run_id=run_id or str(uuid4()),
            workflow_input=workflow_input,
            state=WorkflowState(dict(state or {})),
            node_results={node.node_id: NodeResult(node.node_id) for node in workflow.nodes},
        )
        return await self._drive(workflow, run, resumed=False)

    async def resume(
        self,
        workflow: Workflow,
        checkpoint: WorkflowRun | str | Mapping[str, Any],
    ) -> WorkflowRun:
        if isinstance(checkpoint, str):
            run = WorkflowRun.from_json(checkpoint)
        elif isinstance(checkpoint, WorkflowRun):
            run = WorkflowRun.from_dict(checkpoint.to_dict())
        else:
            run = WorkflowRun.from_dict(checkpoint)
        workflow.validate()
        if run.workflow_id != workflow.workflow_id:
            raise WorkflowError("checkpoint belongs to a different workflow")
        expected = {node.node_id for node in workflow.nodes}
        if set(run.node_results) != expected:
            raise WorkflowError("checkpoint nodes do not match the workflow")
        if run.status == WorkflowStatus.COMPLETED:
            return run
        for result in run.node_results.values():
            if result.status != NodeStatus.COMPLETED:
                result.status = NodeStatus.PENDING
                result.error = None
                result.started_at = None
                result.completed_at = None
        run.status = WorkflowStatus.PENDING
        run.error = None
        run.completed_at = None
        return await self._drive(workflow, run, resumed=True)

    async def cancel(self, run_id: str) -> bool:
        request = self._cancel_requests.get(run_id)
        if request is None:
            return False
        request.set()
        for task in tuple(self._node_tasks.get(run_id, ())):
            task.cancel()
        return True

    async def _drive(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        *,
        resumed: bool,
    ) -> WorkflowRun:
        cancel_request = asyncio.Event()
        self._cancel_requests[run.run_id] = cancel_request
        self._node_tasks[run.run_id] = set()
        run.status = WorkflowStatus.RUNNING
        await self._emit(run, "workflow.resumed" if resumed else "workflow.started")
        await self._checkpoint(run)
        try:
            while True:
                pending = [
                    node for node in workflow.nodes
                    if run.node_results[node.node_id].status == NodeStatus.PENDING
                ]
                if not pending:
                    break
                if cancel_request.is_set():
                    return await self._interrupt(run)
                ready, skipped = self._ready_nodes(workflow, run, pending)
                for node in skipped:
                    result = run.node_results[node.node_id]
                    result.status = NodeStatus.SKIPPED
                    result.completed_at = _utc_now()
                    await self._emit(run, "node.skipped", node.node_id)
                if skipped:
                    await self._checkpoint(run)
                    continue
                if not ready:
                    raise WorkflowError("workflow cannot make progress from its checkpoint")
                semaphore = asyncio.Semaphore(self.max_concurrency)
                tasks = {
                    asyncio.create_task(self._execute_node(workflow, run, node, semaphore))
                    for node in ready
                }
                self._node_tasks[run.run_id].update(tasks)
                try:
                    await asyncio.gather(*tasks)
                except asyncio.CancelledError:
                    if cancel_request.is_set():
                        return await self._interrupt(run)
                    await self._interrupt(run)
                    raise
                finally:
                    self._node_tasks[run.run_id].difference_update(tasks)
                await self._checkpoint(run)
                failures = [
                    result for result in run.node_results.values()
                    if result.status == NodeStatus.FAILED
                ]
                if failures:
                    run.status = WorkflowStatus.FAILED
                    run.error = "; ".join(f"{item.node_id}: {item.error}" for item in failures)
                    run.completed_at = _utc_now()
                    await self._emit(run, "workflow.failed", payload={"error": run.error})
                    await self._checkpoint(run)
                    return run
            run.status = WorkflowStatus.COMPLETED
            run.completed_at = _utc_now()
            await self._emit(run, "workflow.completed")
            await self._checkpoint(run)
            return run
        finally:
            self._cancel_requests.pop(run.run_id, None)
            self._node_tasks.pop(run.run_id, None)

    def _ready_nodes(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        pending: Sequence[Node],
    ) -> tuple[list[Node], list[Node]]:
        ready: list[Node] = []
        skipped: list[Node] = []
        for node in pending:
            incoming = [edge for edge in workflow.edges if edge.target == node.node_id]
            if not incoming:
                ready.append(node)
                continue
            sources = [run.node_results[edge.source] for edge in incoming]
            if any(source.status in {NodeStatus.PENDING, NodeStatus.RUNNING} for source in sources):
                continue
            if any(
                not edge.conditional
                and run.node_results[edge.source].status
                in {NodeStatus.FAILED, NodeStatus.INTERRUPTED}
                for edge in incoming
            ):
                skipped.append(node)
                continue
            active = [edge for edge in incoming if self._edge_active(workflow, run, edge)]
            if active:
                ready.append(node)
            else:
                skipped.append(node)
        return ready, skipped

    def _edge_active(self, workflow: Workflow, run: WorkflowRun, edge: Edge) -> bool:
        source = run.node_results[edge.source]
        if source.status != NodeStatus.COMPLETED:
            return False
        if edge.route is not None:
            selected = source.route if source.route is not None else _route_value(source.value)
            return selected == edge.route
        if edge.predicate is not None:
            context = self._context(workflow, run, edge.source, source.attempts, source.iterations)
            return bool(edge.predicate(context, source))
        return True

    async def _execute_node(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        node: Node,
        semaphore: asyncio.Semaphore,
    ) -> None:
        async with semaphore:
            result = run.node_results[node.node_id]
            result.status = NodeStatus.RUNNING
            result.started_at = _utc_now()
            await self._emit(run, "node.started", node.node_id)
            try:
                last_value: Any = None
                last_route: str | None = None
                for iteration in range(1, node.max_iterations + 1):
                    output = await self._invoke_with_retry(workflow, run, node, result, iteration)
                    value, updates, route = _normalize_output(output)
                    run.state.update(updates)
                    last_value = value
                    last_route = route
                    result.iterations = iteration
                    if node.loop_until is None:
                        break
                    context = self._context(workflow, run, node.node_id, result.attempts, iteration)
                    if node.loop_until(context, value):
                        break
                else:
                    raise WorkflowError(
                        f"node {node.node_id!r} reached its max loop iterations "
                        "without satisfying loop_until"
                    )
                declared_routes = {
                    edge.route
                    for edge in workflow.edges
                    if edge.source == node.node_id and edge.route is not None
                }
                if declared_routes:
                    selected = last_route if last_route is not None else _route_value(last_value)
                    if selected not in declared_routes:
                        raise WorkflowError(
                            f"node {node.node_id!r} selected unknown route {selected!r}"
                        )
                    last_route = selected
                result.value = last_value
                result.route = last_route
                result.status = NodeStatus.COMPLETED
                result.completed_at = _utc_now()
                if last_route is not None:
                    await self._emit(
                        run,
                        "route.selected",
                        node.node_id,
                        {"route": last_route},
                    )
                await self._emit(run, "node.completed", node.node_id)
            except asyncio.CancelledError:
                result.status = NodeStatus.INTERRUPTED
                result.error = "node execution interrupted"
                result.completed_at = _utc_now()
                await self._emit(run, "node.interrupted", node.node_id)
                raise
            except Exception as error:  # normalized at the workflow boundary
                result.status = NodeStatus.FAILED
                result.error = f"{type(error).__name__}: {error}"
                result.completed_at = _utc_now()
                await self._emit(
                    run,
                    "node.failed",
                    node.node_id,
                    {"error": result.error, "attempts": result.attempts},
                )

    async def _invoke_with_retry(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        node: Node,
        result: NodeResult,
        iteration: int,
    ) -> object:
        for attempt in range(1, node.retry.max_attempts + 1):
            result.attempts += 1
            context = self._context(workflow, run, node.node_id, attempt, iteration)
            try:
                value = node.handler(context)
                if inspect.isawaitable(value):
                    awaited = cast(Awaitable[object], value)
                    if node.timeout is not None:
                        return await asyncio.wait_for(awaited, node.timeout)
                    return await awaited
                return value
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt >= node.retry.max_attempts:
                    raise
                delay = node.retry.delay(attempt)
                await self._emit(
                    run,
                    "node.retrying",
                    node.node_id,
                    {"attempt": attempt, "delay_seconds": delay, "iteration": iteration},
                )
                if delay:
                    await asyncio.sleep(delay)
        raise AssertionError("retry loop must return or raise")

    def _context(
        self,
        workflow: Workflow,
        run: WorkflowRun,
        node_id: str,
        attempt: int,
        iteration: int,
    ) -> WorkflowContext:
        return WorkflowContext(
            workflow.workflow_id,
            run.run_id,
            node_id,
            run.workflow_input,
            run.state.snapshot(),
            MappingProxyType(dict(run.node_results)),
            attempt,
            iteration,
        )

    async def _interrupt(self, run: WorkflowRun) -> WorkflowRun:
        for result in run.node_results.values():
            if result.status == NodeStatus.RUNNING:
                result.status = NodeStatus.INTERRUPTED
                result.error = "node execution interrupted"
                result.completed_at = _utc_now()
        run.status = WorkflowStatus.INTERRUPTED
        run.error = "workflow execution interrupted"
        run.completed_at = _utc_now()
        await self._emit(run, "workflow.interrupted")
        await self._checkpoint(run)
        return run

    async def _emit(
        self,
        run: WorkflowRun,
        event_type: str,
        node_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        event = WorkflowEvent(
            len(run.events) + 1,
            event_type,
            run.workflow_id,
            run.run_id,
            node_id,
            payload=payload or {},
        )
        run.events.append(event)
        run.updated_at = event.timestamp
        if self.event_listener is not None:
            outcome = self.event_listener(event)
            if inspect.isawaitable(outcome):
                await cast(Awaitable[object], outcome)

    async def _checkpoint(self, run: WorkflowRun) -> None:
        if self.store is not None:
            self.store.save(run)


def _normalize_output(output: object) -> tuple[Any, Mapping[str, Any], str | None]:
    if isinstance(output, NodeOutput):
        return output.value, output.updates, output.route
    return output, {}, None


def _route_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _optional_datetime(value: object) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


def _assert_json_serializable(value: object) -> None:
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise WorkflowError(f"workflow state is not JSON serializable: {error}") from error
