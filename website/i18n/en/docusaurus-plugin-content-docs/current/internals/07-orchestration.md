---
id: internals-07-orchestration
title: Autonomous Orchestration, Deterministic Workflows, and the Hybrid Boundary
sidebar_position: 7
description: "How AgentManager autonomous orchestration, the WorkflowEngine deterministic engine, and the hybrid boundary work internally: data model, lifecycle, concurrency/cancellation, persistence, and failure model."
---

# Autonomous Orchestration, Deterministic Workflows, and the Hybrid Boundary

This page is chapter 7 of the Super Harness Internals series. It covers the three main pieces under `src/super_harness/orchestration/`:

- **Autonomous orchestration** — `AgentManager` in `autonomous.py`: manages a bounded concurrent tree of independently configured Agents built by an application factory.
- **Deterministic workflows** — `Workflow` / `WorkflowEngine` / `JSONWorkflowStore` in `workflow.py`: validated DAGs, batched scheduling, atomic checkpoints, and resumable runs.
- **The hybrid boundary** — `AutonomousAgentNode` / `SubworkflowNode` in `hybrid.py`: expose an autonomous Agent subtree and a nested workflow as ordinary workflow nodes.
- Plus `Router` / `Route` / `RouteDecision` in `router.py`: provider-neutral, observable rule routing reused by workflow router nodes.

All three subsystems share one design thread: **separating immutable values from mutable internal state**. For the caller, everything observable is an immutable snapshot, result, or event; mutable task records, batch tasks, and checkpoints stay sealed inside the manager/engine. That thread is what makes concurrency safety, cancellation, and persistence possible, and it is also what keeps "usage" and "internals" cleanly apart.

> For a hands-on introduction, read the user guide and the runnable examples. This page explains how things work and why they are designed that way — it is not a tutorial.

---

## 1. Responsibilities

### 1.1 `AgentManager` responsibilities

`AgentManager` is the single entry point for autonomous orchestration. Its boundaries are explicit:

- **Maintain a bounded concurrent Agent tree.** The root Agent is supplied by the caller at construction; every child Agent is created through the application-supplied `AgentFactory` — the manager never constructs concrete Agents itself.
- **Keep mutable task records private** and expose only immutable `AgentSnapshot`, `AgentResult`, and `AgentEvent` values. Callers cannot touch the internal `_ManagedAgent` fields or bypass validation to mutate state.
- **Give every child its own independent `Agent` and `Thread`.** This is what makes concurrency safe and isolation real: each child has its own history, context, and provider, untouched by the parent or siblings.
- **Validate the full limit set before spawning**: non-empty task/role, depth limit, total-agent limit, active-agent limit, global token budget, global time budget, child timeout, and child token budget.
- **Schedule concurrent execution.** `spawn_agent` schedules `_run` as an `asyncio.Task` and returns a snapshot immediately without blocking the caller.
- **Provide selective waiting and event streaming** based on `asyncio.Condition` rather than polling.
- **Accumulate model usage** by reading `Usage` from every `model.completed` event into `_tokens_used`.
- **Bound terminal child output** and populate neutral `Usage`, artifacts/references, and descendant thread IDs.
- **Register collaboration operations as ordinary typed Tools** in the participating Agents' existing registries, thereby reusing validation, approval, timeout, tool-result correlation, and model continuation.
- **Support parent/subtree cancellation (deepest child first) and resume (retaining Thread history).**

### 1.2 `WorkflowEngine` responsibilities

`WorkflowEngine` runs deterministic workflows:

- **Validate structure before any handler runs**: endpoint/identity checks, uniqueness, and a Kahn topological sort (DAG cycle detection).
- **Schedule nodes in dependency batches.** Only nodes whose inbound dependencies have all reached a terminal state and with at least one active inbound edge join a batch; independent nodes become `asyncio.Task`s behind a concurrency semaphore.
- **Mark inactive conditional branches as `skipped`** rather than pretending they ran.
- **Serialize a versioned `WorkflowRun` after each stable batch** and hand it to `JSONWorkflowStore` for atomic writes.
- **Support resume**: keep completed results/state, reset only unfinished, failed, skipped, or interrupted nodes.
- **Publish events with a per-run monotonic sequence**, correlating workflow/node lifecycle, routing, retries, failures, and interruptions.
- **Apply retry and loop policies**, and normalize any handler exception into `NodeStatus.FAILED` / `WorkflowError`.

### 1.3 Hybrid node responsibilities

- `AutonomousAgentNode` runs one `AgentManager` subtree as an ordinary workflow node. It **delegates to the real `AgentManager`** — it neither simulates a model response nor bypasses Tool execution; it waits for the child and all discovered descendants, cancels leftover active stragglers, and forwards metadata only.
- `SubworkflowNode` runs a nested `Workflow` as an ordinary node. It derives a stable child run ID, prefers resuming the child checkpoint, and cascades cancellation into the child engine.

### 1.4 `Router` responsibilities

`Router` owns no provider or workflow state. It converts a value plus an immutable context view into a `RouteDecision`; observation exposes route metadata only. It serves the workflow `NodeKind.ROUTER` scenario and is independently reusable.

---

## 2. Data model

### 2.1 Autonomous orchestration data model

#### Immutable value types (public)

**`AgentStatus`** (`StrEnum`) is the public status machine:

```python
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
```

`PENDING`, `RUNNING`, and `WAITING` are the "active" states (module constant `_ACTIVE = frozenset({...})`); `wait` / `wait_all` use them to decide readiness.

**`ContextInheritance`** (`StrEnum`) controls context inheritance:

```python
class ContextInheritance(StrEnum):
    MINIMAL = "minimal"   # default: inherit no context fragments
    SELECTED = "selected" # inherit only the sources named in selected_sources
    FULL = "full"         # inherit all fragments plus parent history (appended as a MEMORY fragment)
```

**`MultiAgentLimits`** (frozen dataclass) defines the manager's global/default limits:

```python
@dataclass(frozen=True, slots=True)
class MultiAgentLimits:
    max_active_agents: int = 4          # simultaneous active Agents
    max_total_agents: int = 16          # total Agents in the tree (excluding root)
    max_depth: int = 3                  # maximum depth (root is 0)
    total_token_budget: int = 100_000   # global token budget
    total_timeout: float = 3_600.0      # global time budget (seconds)
    default_agent_timeout: float = 300.0
    max_result_chars: int = 20_000      # terminal result text truncation cap
```

`__post_init__` validates that count/depth/token/char bounds are positive and both timeouts are positive. Violations raise `ValueError`.

**`SpawnRequest`** (frozen dataclass) is the request value handed to the factory:

```python
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
```

**`AgentResult`** (frozen dataclass) is the terminal result value:

```python
@dataclass(frozen=True, slots=True)
class AgentResult:
    agent_id: str
    status: AgentStatus
    text: str = ""                    # truncated to max_result_chars
    artifacts: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    child_trace_ids: tuple[str, ...] = ()  # descendant Thread IDs
```

**`AgentEvent`** (frozen dataclass) is a monotonically sequenced event value; `payload` is frozen into a `MappingProxyType`:

```python
@dataclass(frozen=True, slots=True)
class AgentEvent:
    sequence: int
    type: str
    agent_id: str
    parent_agent_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    payload: Mapping[str, Any] = field(default_factory=_payload)
```

**`AgentSnapshot`** (frozen dataclass) is the read-only view of an Agent at a point in time:

```python
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
```

#### Mutable internal type (private)

**`_ManagedAgent`** (non-frozen dataclass) is the mutable task record inside the manager. It holds direct references to the `Agent` and `Thread`, mutable status fields, `task_handle: asyncio.Task | None`, and `interrupt_requested: bool`. Its `snapshot()` method projects the current state into an immutable `AgentSnapshot`. **Callers never see `_ManagedAgent`** — every public operation returns snapshots.

### 2.2 Workflow data model

#### Structural declarations (frozen, validated at construction)

**`NodeKind`** (`StrEnum`): `FUNCTION`, `TOOL`, `AGENT`, `ROUTER`, `SUBWORKFLOW`, `TRANSFORM`, `GATE`.

**`NodeStatus`** (`StrEnum`): `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `SKIPPED`, `INTERRUPTED`.

**`WorkflowStatus`** (`StrEnum`): `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `INTERRUPTED`.

**`Node`** (frozen dataclass):

```python
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
```

`Node.__post_init__` enforces several key invariants:
- `node_id` is non-empty.
- `timeout`, when given, must be positive.
- `max_iterations >= 1`.
- **`max_iterations` must equal 1 when `loop_until` is `None`** (otherwise the extra iterations serve no purpose).
- **`retry.max_attempts > 1` requires an explicit `idempotent=True`** — the engine refuses to retry a node that does not declare idempotency.

**`Edge`** (frozen dataclass):

```python
@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    route: str | None = None
    predicate: EdgePredicate | None = None
```

`Edge.__post_init__`: both endpoints are non-empty; **`route` and `predicate` cannot be declared together**. `conditional` is `True` when the edge is conditional (has a `route` or a `predicate`).

**`RetryPolicy`** (frozen dataclass):

```python
@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0
    multiplier: float = 2.0
    max_backoff_seconds: float = 60.0

    def delay(self, failed_attempt: int) -> float:
        delay = self.backoff_seconds * self.multiplier ** max(0, failed_attempt - 1)
        return min(delay, self.max_backoff_seconds)
```

`delay` computes exponential backoff capped at `max_backoff_seconds`.

**`NodeOutput`** (frozen dataclass) is the optional structured return of a handler:

```python
@dataclass(frozen=True, slots=True)
class NodeOutput:
    value: Any = None
    updates: Mapping[str, Any] = field(default_factory=_values)  # merged atomically into run.state
    route: str | None = None
```

A handler returning a plain value is interpreted as `value` only (`updates` empty, `route` `None`); returning `NodeOutput` uses all three fields.

#### Runtime types

**`WorkflowContext`** (frozen dataclass) is what handlers receive:

```python
@dataclass(frozen=True, slots=True)
class WorkflowContext:
    workflow_id: str
    run_id: str
    node_id: str
    workflow_input: Any
    state: Mapping[str, Any]          # read-only snapshot of run.state
    results: Mapping[str, NodeResult] # read-only view of run.node_results
    attempt: int
    iteration: int
    emit: Callable[[str, Mapping[str, Any]], Awaitable[None]]  # node-local event emission
```

**`NodeResult`** (mutable dataclass with `to_dict`/`from_dict`):

```python
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
```

**`WorkflowEvent`** (frozen dataclass with `to_dict`/`from_dict`): `sequence` is monotonically increasing per run (starting at 1) alongside `workflow_id`, `run_id`, `node_id`, `timestamp`, and `payload`.

**`WorkflowState`** (mutable dataclass): wraps `values: dict` with `update(values)` and `snapshot()` (returns `MappingProxyType`).

**`WorkflowRun`** (mutable, serializable):

```python
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
```

The `output` property returns the `value` of the last `COMPLETED` node. `to_dict` writes `schema_version: 1` and asserts the whole structure is JSON-serializable (otherwise `WorkflowError`); `to_json` serializes with `ensure_ascii=False`.

**`Workflow`** (frozen dataclass, validated at construction) holds `workflow_id`, `nodes: tuple[Node, ...]`, `edges: tuple[Edge, ...]`. Its custom `__init__` calls `self.validate()` immediately.

### 2.3 Hybrid boundary data model

- `AutonomousAgentNode` holds `manager`, `task: PromptBuilder`, `role`, `parent_agent_id`, `instructions`, `inheritance`, `selected_sources`, `timeout`, `token_budget`, plus a private `_agent_ids: dict[run_id, agent_id]` mapping workflow runs to the delegated Agent.
- `SubworkflowNode` holds `workflow`, `engine`, `input_builder`, `state_builder`, plus a private `_active_runs: dict[run_id, child_run_id]`.
- `PromptBuilder = str | Callable[[WorkflowContext], str]`, `InputBuilder = Callable[[WorkflowContext], Any]`, `StateBuilder = Callable[[WorkflowContext], Mapping[str, Any]]`.

### 2.4 Routing data model

**`Route`** (frozen dataclass): `name`, `target`, `predicate: RoutePredicate[T]`, `priority: int = 100`, `metadata`. Construction requires non-empty name/target and a callable predicate.

**`RouteDecision`** (frozen dataclass): `route`, `target`, `matched: bool`, `reason`, `timestamp`, `metadata`.

**`Router`**: holds `routes` sorted by `(priority, name)`, `default`, and `observer`.

---

## 3. Lifecycle

### 3.1 `AgentManager` lifecycle

```
Construct AgentManager
   │  pass root_agent + factory + limits + hooks + event_listener
   ├─ generate root_agent_id = uuid4()
   ├─ if expose_tools: register collaboration Tools into root_agent's registry
   ├─ root_thread = root_agent.thread(); record root_thread_id
   └─ build _agents = {root_agent_id: _ManagedAgent(status=ROOT, depth=0)}

spawn_agent(parent, task, ...)
   ├─ validate task/role non-empty
   ├─ depth = parent.depth + 1; over limit → MultiAgentError
   ├─ validate total/active agent counts → MultiAgentError
   ├─ _check_global_budget() (token/time)
   ├─ validate child_timeout / token_budget
   ├─ compute inherited context (MINIMAL/SELECTED/FULL)
   ├─ factory(request) builds the child Agent (failure → MultiAgentError("child Agent factory failed"))
   ├─ if expose_tools: register collaboration Tools into the child's registry
   ├─ build _ManagedAgent(PENDING), register in _agents, append to parent.child_agent_ids
   ├─ _emit("agent.spawned") + dispatch(SUBAGENT_START)
   │     └─ hook failure: remove from _agents and parent.child_agent_ids → MultiAgentError
   ├─ schedule self._run(child, task) as an asyncio.Task
   └─ return child.snapshot()

_run(child, prompt)  [asyncio.Task]
   ├─ status = RUNNING; _emit("agent.started")
   ├─ async with asyncio.timeout(min(child.timeout, remaining global seconds)):
   │     iterate child.thread.astream(prompt)
   │       ├─ _emit_thread_event(...) (filters model.text/tool_call deltas by default)
   │       ├─ model.completed → accumulate usage
   │       └─ turn.completed → record response
   ├─ empty response → MultiAgentError
   ├─ _tokens_used += usage.total_tokens
   ├─ pick terminal state: COMPLETED / BUDGET_EXHAUSTED (child or global budget exceeded)
   ├─ child.result = _result(...) (truncate text, parse artifacts/references from output_json, fill child_trace_ids)
   ├─ _emit("agent.completed", {result})
   ├─ exception branches: CancelledError→INTERRUPTED/CANCELLED; TimeoutError→FAILED("agent timed out"); other→FAILED
   └─ finally: dispatch(SUBAGENT_END); notify _completion_condition
        (SUBAGENT_END hook failure → node FAILED but waiters are still notified)

wait / wait_all
   └─ if targets not ready: async with _completion_condition: await wait_for(condition.wait_for(ready), timeout)

send_input / resume_agent / interrupt_agent / cancel / close_agent
   └─ mutate state as needed and _emit the matching event
```

Key timing facts:
- **Spawn hook failure is "first, remove"**: a failed `SUBAGENT_START` removes the pending record (no orphan) and surfaces as `MultiAgentError` to the caller.
- **`_run` is a self-contained task**: whether it succeeds, is cancelled, times out, or raises, the `finally` block dispatches `SUBAGENT_END` and notifies the completion condition, so waiters can never hang.
- **Interrupt and cancel are different terminations**: `interrupt_agent` targets one active child, sets `interrupt_requested`, then `task_handle.cancel()`; `cancel` targets a subtree and cancels each task from the deepest descendant upward.

### 3.2 `WorkflowEngine` execution lifecycle

```
run(workflow, workflow_input, *, state, run_id)
   ├─ workflow.validate()                       # already run at construction; run again here
   ├─ construct WorkflowRun (PENDING, all node_results PENDING)
   └─ _drive(workflow, run, resumed=False)

resume(workflow, checkpoint)
   ├─ deserialize checkpoint (str/WorkflowRun/dict)
   ├─ workflow.validate()
   ├─ validate checkpoint.workflow_id matches workflow → else WorkflowError
   ├─ validate checkpoint node set == workflow node set → else WorkflowError
   ├─ if checkpoint already COMPLETED → return it
   ├─ reset every non-COMPLETED node to PENDING (clear error/started/completed)
   ├─ run.status = PENDING; clear error/completed_at
   └─ _drive(workflow, run, resumed=True)

_drive(workflow, run, *, resumed)
   ├─ register cancel_request Event and node_tasks set
   ├─ run.status = RUNNING; _emit("workflow.resumed"/"workflow.started"); _checkpoint()
   └─ main loop:
        pending = all nodes with status == PENDING
        if pending empty → break
        if cancel_request set → _interrupt(run), return
        (ready, skipped) = _ready_nodes(...)
           ├─ skipped: mark SKIPPED, _emit("node.skipped"); if any skipped this round, _checkpoint then continue
           └─ ready empty while pending non-empty → WorkflowError("cannot make progress")
        wrap each ready node as a Task behind asyncio.Semaphore(max_concurrency)
        await asyncio.gather(*tasks)
           └─ catch CancelledError: explicit cancel → _interrupt and return; otherwise _interrupt then re-raise
        _checkpoint()
        if any FAILED node → run=FAILED, join errors, _emit("workflow.failed"), _checkpoint, return
        loop
   run.status = COMPLETED; _emit("workflow.completed"); _checkpoint; return
   finally: clean up _cancel_requests / _node_tasks
```

**`_ready_nodes` readiness**: 
- A node with no inbound edges is ready.
- If any inbound source is still PENDING/RUNNING, the node waits (not in this batch).
- If any non-conditional inbound source is FAILED/INTERRUPTED, the node is `skipped`.
- Otherwise compute "active edges": `_edge_active` only applies to `COMPLETED` sources, evaluating `route` equality or `predicate`. Any active edge → ready; else → `skipped`.

**`_execute_node` (single node, with loop and retry)**:
- `result.status = RUNNING`, `started_at`, `_emit("node.started")`.
- Outer `for iteration in 1..max_iterations`: each iteration runs `_invoke_with_retry`, normalizes the output, `run.state.update(updates)`, records `last_value`/`last_route`; breaks when `loop_until` is satisfied; if the loop exhausts without satisfying it → `WorkflowError("reached its max loop iterations")`.
- If the node declares outbound `route`s, the selected route must belong to the declared set, else `WorkflowError("selected unknown route")`.
- Write back `result.value/route/status=COMPLETED/completed_at`; `_emit("route.selected")`, `_emit("node.completed")`.
- Exceptions: `CancelledError` → `INTERRUPTED` and re-raise; anything else → `FAILED` (`_emit("node.failed")`).

**`_invoke_with_retry` (one attempt)**: loops `1..retry.max_attempts`, increments `result.attempts`, builds a `WorkflowContext`, calls `node.handler(context)`; if awaitable, awaits it (wrapped in `asyncio.wait_for` when `node.timeout` is set). `CancelledError` is re-raised immediately; other exceptions below the attempt cap emit `node.retrying` and back off by `delay` before retrying.

### 3.3 Hybrid node lifecycle

**`AutonomousAgentNode.__call__`**:
1. Resolve `task` (evaluate `PromptBuilder` when callable); empty → `WorkflowError`.
2. Record `cursor = max(event_history().sequence)` (only forward events added after this point).
3. `manager.spawn_agent(...)` creates the child; record `run_id → agent_id` in `_agent_ids`.
4. `wait_all([child.agent_id])` for the child; then `wait_all(descendants)` for all descendants.
5. If any snapshot is still active → `manager.cancel(child)` to cancel leftover stragglers.
6. `_forward_agent_events` forwards only metadata events for that subtree.
7. Child not `COMPLETED` or `result is None` → `WorkflowError`.
8. Any failed descendant → `WorkflowError`.
9. Return `NodeOutput(result.text, {hybrid.<node>.agent_id/thread_id/tokens})`.
10. Catch `CancelledError` → `manager.cancel(child)`, forward events, re-raise.

**`SubworkflowNode.__call__`**:
1. `child_run_id = _child_run_id(parent_run_id, node_id)` (`<parent-run>-<safe-node>`).
2. Try `_load_if_present(engine.store, child_run_id)`.
3. Checkpoint present → `engine.resume(workflow, checkpoint)`; otherwise `engine.run(workflow, input_builder(context), state=state_builder?(context), run_id=child_run_id)`.
4. `_forward_subworkflow_events(context, child, after_sequence=len(checkpoint.events) if present)`.
5. Not `COMPLETED` → `WorkflowError`.
6. Return `NodeOutput(child.output, {hybrid.<node>.workflow_id/run_id})`.
7. Catch `CancelledError` → `engine.cancel(child_run_id)`, forward the latest checkpoint events, re-raise.

### 3.4 `Router` lifecycle

`aroute(value, *, context)` evaluates each `route.predicate(value, safe_context)` in order (async predicates supported); on a hit it builds `RouteDecision(matched=True)`, `_observe`s, and returns. If nothing matches, it uses `default` (no default → `WorkflowError`). `route(...)` is the sync wrapper: with no running event loop it uses `asyncio.run`; inside an active loop it raises `RuntimeError` demanding `aroute`.

---

## 4. Key interfaces / classes

### 4.1 `AgentManager`

```python
AgentManager(
    root_agent: Agent,
    factory: AgentFactory,
    *,
    limits: MultiAgentLimits | None = None,
    hooks: HookRegistry | None = None,
    event_listener: AgentEventListener | None = None,
    include_child_deltas: bool = False,
    expose_tools: bool = True,
)

async def spawn_agent(self, parent_agent_id: str, task: str, *,
    role: str = "worker", instructions: str | None = None,
    inheritance: ContextInheritance = ContextInheritance.MINIMAL,
    selected_sources: Sequence[str] = (),
    timeout: float | None = None, token_budget: int | None = None) -> AgentSnapshot
async def send_input(self, agent_id: str, message: str) -> AgentSnapshot
async def resume_agent(self, agent_id: str, message: str | None = None) -> AgentSnapshot
async def wait(self, agent_ids: Sequence[str] | None = None, *, timeout: float | None = None) -> tuple[AgentSnapshot, ...]
async def wait_all(self, agent_ids: Sequence[str] | None = None, *, timeout: float | None = None) -> tuple[AgentSnapshot, ...]
async def interrupt_agent(self, agent_id: str) -> AgentSnapshot
async def cancel(self, agent_id: str | None = None) -> None
async def close_agent(self, agent_id: str) -> AgentSnapshot
async def aclose(self) -> None
def list_agents(self, *, parent_agent_id: str | None = None) -> tuple[AgentSnapshot, ...]
def get(self, agent_id: str) -> AgentSnapshot
def thread(self, agent_id: str) -> Thread
def results(self, agent_ids: Sequence[str] | None = None) -> tuple[AgentResult, ...]
def event_history(self, *, after_sequence: int = 0) -> tuple[AgentEvent, ...]
@property def tokens_used(self) -> int
def collaboration_tools(self, parent_agent_id: str) -> tuple[Tool, ...]
async def events(self, *, after_sequence: int = 0) -> AsyncIterator[AgentEvent]
```

`events()` is an async generator built on `_event_condition`: it yields all buffered events after the cursor first, then `await`s the condition for new ones. This is the public "event stream, not polling" surface.

### 4.2 Collaboration Tools

`collaboration_tools(parent_agent_id)` returns six typed Tools defined with `@tool` (`source="multi_agent"`, `risk="runtime"`):

| Tool | Signature | Semantics |
|---|---|---|
| `spawn_agent` | `(task, role="worker", instructions=None, inheritance="minimal", selected_sources=None, timeout=None, token_budget=None) -> AgentSnapshot` | Spawn a child under the given parent and start it concurrently |
| `send_input` | `(agent_id, message) -> AgentSnapshot` | Send steering or queue a follow-up input |
| `wait_agent` | `(agent_ids=None, timeout=30.0) -> list[dict]` | Wait until at least one selected child reaches a terminal state |
| `resume_agent` | `(agent_id, message=None) -> AgentSnapshot` | Resume an inactive child with queued or explicit input |
| `interrupt_agent` | `(agent_id) -> AgentSnapshot` | Interrupt one active child without cancelling its parent |
| `close_agent` | `(agent_id) -> AgentSnapshot` | Close a child subtree while retaining resumable state |

`_attach_tools` registers these into the root's and every child's `tool_registry`. A conflict (`ToolError`) is wrapped as `MultiAgentError("Agent has a conflicting collaboration tool")`.

### 4.3 Workflow

```python
Node(node_id: str, handler: NodeHandler, kind: NodeKind = FUNCTION,
     retry: RetryPolicy = ..., timeout: float | None = None,
     idempotent: bool = False, loop_until: LoopPredicate | None = None,
     max_iterations: int = 1)
Edge(source: str, target: str, route: str | None = None, predicate: EdgePredicate | None = None)
NodeOutput(value: Any = None, updates: Mapping[str, Any] = ..., route: str | None = None)
RetryPolicy(max_attempts=1, backoff_seconds=0.0, multiplier=2.0, max_backoff_seconds=60.0)

Workflow(workflow_id: str, nodes: Sequence[Node], edges: Sequence[Edge] = ())
    def validate(self) -> None
    def node(self, node_id: str) -> Node

JSONWorkflowStore(directory: str | Path)
    def save(self, run: WorkflowRun) -> Path
    def load(self, run_id: str) -> WorkflowRun

WorkflowEngine(*, max_concurrency: int = 8, store: JSONWorkflowStore | None = None,
               event_listener: EventListener | None = None)
    async def run(self, workflow: Workflow, workflow_input: Any = None, *,
                  state: Mapping[str, Any] | None = None, run_id: str | None = None) -> WorkflowRun
    async def resume(self, workflow: Workflow, checkpoint: WorkflowRun | str | Mapping[str, Any]) -> WorkflowRun
    async def cancel(self, run_id: str) -> bool
```

### 4.4 Hybrid factories

```python
agent_node(node_id: str, manager: AgentManager, task: PromptBuilder, *,
           role: str = "worker", parent_agent_id: str | None = None,
           instructions: str | None = None,
           inheritance: ContextInheritance = ContextInheritance.MINIMAL,
           selected_sources: Sequence[str] = (),
           timeout: float | None = None, token_budget: int | None = None) -> Node
# returns Node(node_id, AutonomousAgentNode(...), NodeKind.AGENT, timeout=timeout)

subworkflow_node(node_id: str, workflow: Workflow, *,
                 engine: WorkflowEngine | None = None,
                 input_builder: InputBuilder = _input,
                 state_builder: StateBuilder | None = None) -> Node
# returns Node(node_id, SubworkflowNode(...), NodeKind.SUBWORKFLOW)
```

### 4.5 Routing

```python
Route[T](name: str, target: str, predicate: RoutePredicate[T],
         priority: int = 100, metadata: Mapping[str, Any] = ...)
Router[T](routes: Sequence[Route[T]], *, default: str | None = None,
          observer: EventObserver | None = None)
    async def aroute(self, value: T, *, context: Mapping[str, Any] | None = None) -> RouteDecision
    def route(self, value: T, *, context: Mapping[str, Any] | None = None) -> RouteDecision
```

---

## 5. Concurrency / cancellation

### 5.1 `AgentManager` concurrency model

- **One `asyncio.Task` per child.** `spawn_agent` calls `create_task` before returning, so children start executing concurrently; the caller receives an immediate snapshot.
- **The active-agent limit** is enforced by `_active_count()` (counts `_ACTIVE` states) during spawn and resume.
- **Waiting is Condition-based, not polling.** `wait`/`wait_all` use `_completion_condition`; `_run` calls `notify_all` in its `finally` block. There is no busy-poll loop.
- **Event streaming is Condition-based.** `events()` uses `_event_condition`; `_emit` calls `notify_all` after appending each event.

#### Cancellation semantics

- **`interrupt_agent(agent_id)`**: targets a single active child. Sets `interrupt_requested=True`, then `task_handle.cancel()`, and awaits `_await_cancelled(task_handle)` (suppressing `CancelledError`). Result status: `INTERRUPTED`.
- **`cancel(agent_id=None)`**: targets a subtree. `_subtree` returns the target and all descendants; it cancels **in reversed order (deepest child first)**, then `asyncio.gather(..., return_exceptions=True)` waits for cleanup. This guarantees leaves are cancelled first, so parents do not die with dangling children.
- **`close_agent`**: cancels the subtree, then marks each node `CLOSED`, records `completed_at`, `await thread.aclose()`, and `_emit("agent.closed")`.
- **`aclose`**: `cancel()` everything, then closes every thread and agent.
- Inside `_run`, the `CancelledError` branch distinguishes `INTERRUPTED` (when `interrupt_requested`) from `CANCELLED`.

### 5.2 `WorkflowEngine` concurrency model

- **Dependency-ready nodes run in batches.** Each `_drive` loop iteration computes one batch of `ready` nodes.
- **`asyncio.Semaphore(max_concurrency)`** (default 8) bounds concurrent node execution within a batch.
- **Join readiness** requires every inbound source at a terminal state (no PENDING/RUNNING) and at least one active inbound edge. `test_parallel_nodes_overlap_then_join` verifies the three branches peak at `max_concurrency` and the join aggregates all three results.
- **Loops are node-local**: concurrency has nothing to do with graph cycles; cycles are rejected at `validate`.

#### Cancellation semantics

- **`cancel(run_id)`**: sets the run's `cancel_request` Event and cancels each task in the run's `_node_tasks`. Returns whether the run was registered.
- **Cancellation inside `_drive`**: with `cancel_request` set, `_interrupt(run)` runs and the interrupted run is returned; if `gather` raises `CancelledError` without an explicit cancel, `_interrupt` runs first and the error re-raises (so the caller's task cancellation still leaves an `INTERRUPTED` checkpoint on disk).
- **`_interrupt`**: marks still-`RUNNING` nodes `INTERRUPTED`, the run `INTERRUPTED`, `_emit("workflow.interrupted")`, `_checkpoint`.
- **Node cancellation**: `_execute_node` catches `CancelledError`, marks the node `INTERRUPTED`, and re-raises for the upper layer.
- **Retry cancellation**: `_invoke_with_retry` re-raises `CancelledError` immediately; it never backs off into a retry.

### 5.3 Hybrid cancellation cascade

- `AutonomousAgentNode.cancel(run_id)` resolves the delegated child via `_agent_ids` and calls `manager.cancel(agent_id)`, carrying the workflow cancellation into the Agent subtree. The `CancelledError` branch of `__call__` likewise cancels the subtree before forwarding events.
- `SubworkflowNode.cancel(run_id)` resolves the child run via `_active_runs` and calls `engine.cancel(child_run_id)`. Cancellation propagates through both engines: the child engine writes its `INTERRUPTED` checkpoint first, then the parent engine records the parent node as `INTERRUPTED`.

---

## 6. Persistence

### 6.1 `AgentManager` persistence boundary

`AgentManager` itself does **not** write to disk. Its persistence vehicle is each child's independent `Thread` (the durable history provided by `SQLiteThreadStore`). Resume retains that same Thread history: `resume_agent` re-schedules `_run` and continues the same Thread from queued messages, so `turn_count` grows and context/history carry forward. Cross-process state recovery arrives with the persistence extension (see the persistence chapter).

### 6.2 `WorkflowEngine` persistence

- **`WorkflowRun.to_dict/to_json`** is a fully versioned serialization: `schema_version: 1` + `workflow_id` + `run_id` + `workflow_input` + `state` + `node_results` + `status` + `events` + timestamps + `error`. Before serializing, `_assert_json_serializable` rejects any non-serializable state value (raises `WorkflowError`).
- **`JSONWorkflowStore`** writes per `run_id` using an **atomic replace**:

```python
def save(self, run: WorkflowRun) -> Path:
    path = self._path(run.run_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(run.to_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
```

It writes `run_id.json.tmp` first, then `replace`s it to `run_id.json`, so a half-written checkpoint is never observed.
- **`_path` allowlist**: `run_id` permits only alphanumerics, `-`, and `_`, ruling out path traversal (`test_checkpoint_rejects_non_json_state_and_path_traversal` covers `"../escape"`).
- **Checkpoint timing**: `_drive` checkpoints after `workflow.started/resumed`, after every stable batch, and on failure/interrupt/completion. With `store=None` nothing is written (in-memory mode).

### 6.3 Resume semantics

The core rules of `resume`:
- **Completed nodes are retained**: `COMPLETED` nodes' `value`/state are not reset and their handlers do not re-run.
- **Unfinished/failed/skipped/interrupted nodes reset to PENDING**, clearing `error`/`started_at`/`completed_at`.
- **Run-level reset**: `status=PENDING`, clear `error` and `completed_at`.
- The checkpoint's `workflow_id` and node set must exactly match the workflow, else `WorkflowError`.
- An already-`COMPLETED` run is returned without re-execution.

`test_failure_checkpoint_can_resume_without_replaying_completed_nodes` verifies: after resuming a failed run, `first` runs once, `second` runs twice, and state keeps `{"saved": True}`.

### 6.4 Hybrid persistence

- `SubworkflowNode` reuses the child `JSONWorkflowStore`: a repeated parent resumes that checkpoint and forwards only events newer than the loaded snapshot (`after_sequence = len(checkpoint.events)`).
- `AutonomousAgentNode` likewise forwards only events added after its `cursor`.

---

## 7. Events / observability

### 7.1 `AgentManager` events

`AgentEvent.sequence` is **monotonically increasing** within the manager (`self._sequence += 1`). Event types:

| Event | Trigger |
|---|---|
| `agent.spawned` | after a successful spawn registration (includes role/depth) |
| `agent.started` | `_run` enters RUNNING |
| `agent.event` | forwarded child Thread event (filters `model.text.delta` / `model.tool_call.delta` by default) |
| `agent.message` | `send_input` |
| `agent.resumed` | `resume_agent` |
| `agent.completed` | normal completion (includes result) |
| `agent.failed` | timeout, exception, or SUBAGENT_END hook failure |
| `agent.interrupted` / `agent.cancelled` / `agent.budget_exhausted` | matching terminal states |
| `agent.closed` | `close_agent` |

Consumption:
- `event_history(after_sequence=0)` pulls history.
- `events(after_sequence=0)` pulls history and keeps waiting for new events (async generator).
- `event_listener` is invoked synchronously inside `_emit`; an awaitable return value is awaited.
- **`include_child_deltas=False` (default) filters child text/token deltas**, so parents receive bounded results and aggregated lifecycle events. The collaboration `wait_agent` tool returns `asdict(snapshot)` lists.

### 7.2 `WorkflowEngine` events

`WorkflowEvent.sequence` increments per run starting at 1 (`len(run.events) + 1`), correlating `workflow_id`/`run_id`/`node_id`. Types: `workflow.started`, `workflow.resumed`, `workflow.completed`, `workflow.failed`, `workflow.interrupted`, `node.started`, `node.completed`, `node.failed`, `node.skipped`, `node.interrupted`, `node.retrying`, `route.selected`. The `event_listener` callback supports sync/async handlers. `WorkflowContext.emit` lets handlers raise node-local events, all recorded into the same `run.events`.

### 7.3 Hybrid event bridging

- **Agent → workflow**: `_forward_agent_events` forwards only events of the relevant subtree; `payload` carries `source="autonomous_agent"`, `agent_sequence`, `agent_id`, `parent_agent_id`, but **omits child text/token payloads** (IDs and lifecycle types only). Bridged events have `node_id` set to their owning workflow node.
- **Subworkflow → workflow**: `_forward_subworkflow_events` forwards child-run events prefixed `subworkflow.<type>`, with `payload` carrying `source="subworkflow"`, `child_workflow_id`, `child_run_id`, `child_sequence`, `child_node_id`, filtered by `after_sequence`.

### 7.4 `Router` observation

`Router` exposes an `observer: EventObserver` that receives `Event("route.selected", payload={route, target, matched, reason, metadata})` via `_observe` (sync or async), carrying route metadata only — never the routed value itself.

---

## 8. Codex reference

This design was distilled from reverse-engineering Codex source and tests; full records live in `docs/research/codex/`:

- **Autonomous multi-agent**: `docs/research/codex/autonomous-multi-agent.md`. Derived from `codex-rs/core/src/session/multi_agents.rs`, `tools/handlers/multi_agents_common.rs`, `multi_agents/spawn.rs`, `send_input.rs`, `wait.rs`, `resume_agent.rs`, `close_agent.rs`, `multi_agents_v2/interrupt_agent.rs` and their tests. Behavioral contract: model-callable spawn/message/wait/resume/interrupt/close; children run concurrently, may spawn descendants, keep independent threads/configuration, inherit only requested context, and report bounded terminal results; wait is selective and event-driven; cancellation/close cascade subtrees.
- **Deterministic workflow**: `docs/research/codex/deterministic-workflow.md`. Derived from `codex-rs/protocol/src/plan_tool.rs`, `core/src/tools/handlers/plan.rs`, `plan_spec.rs`, `session/turn.rs`, `base_instructions/default.md`. Conclusion: Codex's `update_plan` is a checklist, not an executable graph; Super Harness adopts its contract of strict parsing, explicit state transitions, and event publication, but extends it into a real executable DAG engine.
- **Hybrid orchestration**: `docs/research/codex/hybrid-orchestration.md`. Combines the above two: reuse the autonomous Agent lifecycle, promote the plan surface from "checklist" to "executable workflow", and bridge the two.

---

## 9. Python-native redesign

- **Rust protocol enums and services are replaced by Python dataclass values.** `AgentStatus`/`NodeStatus`/`WorkflowStatus` are `StrEnum`s; `AgentSnapshot`/`AgentResult`/`AgentEvent`/`WorkflowRun`/`NodeResult`/`WorkflowEvent` are immutable or serializable dataclasses. No Codex `SessionSource`, `EventMsg::PlanUpdate`, or `ModeKind`.
- **Collaboration does not depend on a dedicated service.** Codex couples collaboration to Rust session services; Super Harness makes collaboration operations ordinary `@tool`s registered in the existing `ToolRegistry`, so validation, approval, timeout, tool-result correlation, and model continuation apply automatically.
- **The workflow engine needs no model provider.** `WorkflowEngine` only runs Python handlers; nodes may call any application function. `WorkflowContext` is a provider-neutral Python value.
- **Serialization is JSON, not a wire protocol.** `WorkflowRun`/`WorkflowEvent`/`NodeResult` provide `to_dict`/`from_dict`; checkpoints use `json.dumps(..., ensure_ascii=False)` with atomic writes.
- **Concurrency uses `asyncio` primitives**: `asyncio.Task`, `asyncio.Condition`, `asyncio.Semaphore`, `asyncio.Event`, `asyncio.timeout` — no bespoke thread pools or pollers.

---

## 10. Intentional differences

- **Wait uses Conditions, not polling**: Codex's wait semantics are reimplemented with `asyncio.Condition.wait_for(ready)`; event streaming is Condition-based too.
- **`_ManagedAgent` is private; snapshots are public**: callers only ever see immutable snapshots, so runtime state cannot be mutated from outside.
- **Child deltas are hidden by default**: with `include_child_deltas=False`, parents do not receive `model.text.delta`/`model.tool_call.delta`, so parents are not flooded by child token streams.
- **Retry requires an explicit idempotency declaration**: a deliberate departure from reckless retrying. `Node` construction raises `ValueError` when `retry.max_attempts>1` and `idempotent=False`.
- **Loops are node-local and must be bounded**: graph back-edges are rejected at `validate`; loops exist only inside a single node and require a `max_iterations` cap and a `loop_until` predicate.
- **Inactive branches are marked `skipped`, not "pretend success"**: the selected branch can re-join, and unselected handlers are never reported as having run.
- **`Router.route` is forbidden inside an active event loop**: it forces `aroute`, avoiding an implicit `asyncio.run` inside a loop that would raise `RuntimeError`.

---

## 11. Failure model

### 11.1 Autonomous orchestration

- **`MultiAgentError`** (extends `SuperHarnessError`) covers all orchestration contract/limit violations:
  - empty task/role, unknown agent, child-required operations, resuming an active agent, resume without input.
  - depth/total/active agent limits, token budget exhausted, time budget exhausted.
  - `SUBAGENT_START` hook failure (the pending record is removed first, then raised), collaboration tool conflicts.
- **Child terminal states**: timeout → `AgentStatus.FAILED` (error `"agent timed out"`); handler/stream exception → `FAILED` (error like `TypeError: msg`); `CancelledError` → `INTERRUPTED` (when `interrupt_requested`) or `CANCELLED`; budget exceeded → `BUDGET_EXHAUSTED`.
- **`SUBAGENT_END` hook failure**: marks the node `FAILED` with `"subagent end hook failed: ..."`, but **still notifies waiters** — waiting never hangs because of a hook failure.
- **Timeout**: `asyncio.timeout(min(child.timeout, remaining global seconds))`. Both the child timeout and the global time budget apply; the smaller wins.

### 11.2 Workflow

- **`WorkflowError`** (extends `SuperHarnessError`) covers structural/runtime errors: empty workflow_id, empty node set, duplicate nodes, edges referencing unknown nodes, self cycles, graph cycles, non-progressing checkpoints, unknown routes, exhausted loops, non-serializable state, invalid run IDs, mismatched checkpoints.
- **Node failure**: any handler exception is caught by `_execute_node` and normalized to `NodeResult.status = FAILED`, `error = f"{TypeError.__name__}: {msg}"`, `_emit("node.failed")`. After a batch, any `FAILED` node makes the whole run `WorkflowStatus.FAILED` (`error` joins the failing nodes).
- **Timeout**: `node.timeout` applies via `asyncio.wait_for`; `TimeoutError` is treated as a node failure (`test_timeout_is_normalized_as_node_failure` asserts `"TimeoutError"` appears in `run.error`).
- **Retry**: `_invoke_with_retry` backs off per `RetryPolicy.delay` below `max_attempts`; `CancelledError` is never retried.
- **Interruption**: cancellation yields `INTERRUPTED` (node and run level), the checkpoint is written synchronously, and the run can be resumed later.

### 11.3 Hybrid boundary

- `AutonomousAgentNode`: child or any descendant not `COMPLETED` → `WorkflowError("autonomous agent node failed: ...")` / `"autonomous agent descendant failed: ..."`; empty task → `WorkflowError`.
- `SubworkflowNode`: child run not `COMPLETED` → `WorkflowError(f"subworkflow failed: {error or status}")`.
- Cancellation propagates through both layers: parent `WorkflowEngine.cancel` → `SubworkflowNode.cancel` → child `WorkflowEngine.cancel`; parent cancel → `AutonomousAgentNode.cancel` → `AgentManager.cancel`.

---

## 12. Extension points

- **`AgentFactory` (`Callable[[SpawnRequest], Agent]`)**: the primary extension point of autonomous orchestration. The factory decides each child's provider, instructions, and context — see `examples/43_autonomous_research.py` for a typical implementation using `request.instructions` and `request.inherited_context`.
- **`HookRegistry` + `HookEvent.SUBAGENT_START`/`SUBAGENT_END`**: insert auditing, logging, or guardrails at child start/end.
- **`event_listener` / `events()`**: plug in custom event consumption (streaming UI, tracing).
- **`include_child_deltas` / `expose_tools`**: toggles for whether parents receive child token streams and whether collaboration Tools are exposed to Agents.
- **`MultiAgentLimits`**: override global concurrency/budget policy.
- **`WorkflowEngine(max_concurrency, store, event_listener)`**: concurrency, persistence, and events are all replaceable.
- **`JSONWorkflowStore`**: swappable for other backends (implement `save`/`load`).
- **`NodeKind` + factories**: `agent_node`/`subworkflow_node` are ready-made node factories; custom `NodeKind`s can be added.
- **`Router` and `Route`**: predicates support sync/async and work for any value-routing scenario.
- **`input_builder` / `state_builder`**: `SubworkflowNode` derives the child workflow's input/initial state dynamically from the parent context.

---

## 13. Tests

Corresponding test files (`tests/`):

- **`tests/test_autonomous.py`**:
  - `test_spawn_three_concurrently_selective_wait_aggregate_and_trace_tree`: concurrent spawn, selective wait, result aggregation, monotonic event sequences, default delta filtering.
  - `test_model_autonomously_spawns_waits_and_aggregates_via_tools`: the model orchestrates through `spawn_agent`/`wait_agent` tools.
  - `test_send_resume_close_and_structured_result`: send/resume/close lifecycle and turn counting.
  - `test_interrupt_and_parent_cancel_propagate_to_subtree`: single-point interrupt; cancel cascades into the subtree.
  - `test_depth_active_total_timeout_failure_and_budget_guards`: every limit and budget guard.
  - `test_context_inheritance_and_subagent_hooks`: the three inheritance policies and SUBAGENT_START/END hook counts.
  - `test_subagent_hook_failure_does_not_orphan_or_block_wait`: START hook failure leaves no orphan; END hook failure does not block waiting.
- **`tests/test_workflow.py`**:
  - sequential state/results, parallel join peak, conditional route skipping, router events, unknown-route failure, retry backoff and the idempotency contract, loop termination and the strict guard, DAG validation (unknown nodes/duplicates/cycles), failed-checkpoint resume without replay, public-cancel interruption and checkpoint resume, caller-task cancellation persisting interruption, timeout normalized as failure, predicate edges and async listeners, checkpoint rejecting non-JSON state and path traversal.
- **`tests/test_hybrid.py`**:
  - Agent node running inside a sequence and bridging events, subworkflow returning output/state/correlated events, a workflow Agent autonomously invoking a specialist team, workflow cancel cascading into the Agent subtree, parent cancel interrupting and checkpointing the subworkflow, failed subworkflow resuming a stable child checkpoint.
- **`tests/test_autonomous_e2e.py`**: end-to-end path.

---

## 14. Limitations / future work

- **`AgentManager` does not itself persist across processes**; today cross-process recovery relies on `Thread` persistence (`SQLiteThreadStore`) and the evolution of the persistence extension.
- **Workflow graphs do not support back-edges**; loops are deliberately node-local and strictly bounded. More complex shapes (e.g., nested or dynamically generated graphs) are outside the current `validate` scope.
- **`WorkflowRun` checkpoints are whole-batch snapshots**: full serialization per stable batch can carry I/O cost on very large graphs; incremental/sharded checkpoints are possible future work.
- **`AutonomousAgentNode` bounded waiting depends on `timeout`**: if a child and its descendants do not converge within the timeout, the node cancels stragglers and fails — a deliberate safety net, but it can cut off long-tailed work.
- **`Router` evaluates linearly** (in priority/name order); very large route sets lack indexing/sharding.
- **`FULL` context inheritance concatenates all parent history into one `MEMORY` fragment**, which can amplify token cost for long histories.

---

## Related links

- Runnable examples: `examples/43_autonomous_research.py`, `examples/47_agent_budget_cancel.py`, `examples/48_workflow_sequence.py`, `examples/49_workflow_parallel.py`, `examples/50_workflow_conditional.py`, `examples/51_workflow_router.py`, `examples/52_workflow_retry_loop.py`, `examples/53_hybrid_agent_node.py`, `examples/54_hybrid_subworkflow.py`, `examples/55_hybrid_specialist_team.py`, `examples/56_hybrid_failure_resume.py`
- Codex references: `docs/research/codex/autonomous-multi-agent.md`, `docs/research/codex/deterministic-workflow.md`, `docs/research/codex/hybrid-orchestration.md`
- Source: `src/super_harness/orchestration/` (`autonomous.py`, `workflow.py`, `hybrid.py`, `router.py`)