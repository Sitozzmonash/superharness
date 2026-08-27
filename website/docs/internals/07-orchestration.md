---
id: internals-07-orchestration
title: 自主编排、确定性工作流与混合边界
sidebar_position: 7
description: 深入讲解 AgentManager 自主编排、WorkflowEngine 确定性工作流与混合边界的内部原理：数据模型、生命周期、并发取消、持久化与失败模型。
---

# 自主编排、确定性工作流与混合边界

本页是 Super Harness 内部实现（Internals）系列的第七章，覆盖 `src/super_harness/orchestration/` 下的三大块：

- **自主编排（Autonomous orchestration）** —— `autonomous.py` 中的 `AgentManager`：管理一棵有界并发的、由应用工厂构造的独立 Agent 子树。
- **确定性工作流（Deterministic workflow）** —— `workflow.py` 中的 `Workflow` / `WorkflowEngine` / `JSONWorkflowStore`：验证 DAG、按批次调度、原子检查点与可恢复运行。
- **混合边界（Hybrid boundary）** —— `hybrid.py` 中的 `AutonomousAgentNode` / `SubworkflowNode`：把自主 Agent 与嵌套工作流当作普通工作流节点接入。
- 以及 `router.py` 中的 `Router` / `Route` / `RouteDecision`：provider 无关的、可观测的规则路由，供工作流路由节点复用。

这三个子系统共享同一条设计主线：**把不可变的值与可变的内部状态分开**。对调用方而言，你拿到的是不可变的快照、结果与事件；可变的任务记录、批处理任务与检查点永远封闭在管理器/引擎内部。这条主线保证了并发安全、可取消、可持久化，也让「用法与原理分离」成为可能。

> 想快速上手这几个功能，请阅读用户指南与以下可运行示例。本页只讲「怎么工作、为何这样设计」，不讲操作教程。

---

## 1. 职责（Responsibilities）

### 1.1 `AgentManager` 的职责

`AgentManager` 是自主编排的唯一入口。它的职责边界非常明确：

- **维护一棵有界并发的 Agent 树**。根 Agent 在构造时由调用方传入；其余子级 Agent 一律通过应用提供的 `AgentFactory` 工厂创建，管理器不负责构造任何具体 Agent。
- **把可变的任务记录保持私有**，对外只暴露不可变的 `AgentSnapshot`、`AgentResult`、`AgentEvent`。调用方无法触及内部 `_ManagedAgent` 的字段，也不能绕过检查直接改写状态。
- **每个子级拥有独立的 `Agent` 与 `Thread`**。这保证了并发安全与隔离：每个子级有自己独立的历史、上下文与 provider，不会被父级或其他兄弟污染。
- **在 spawn 前校验完整限制集**：非空 task/role、深度限制、总 Agent 数限制、活动 Agent 数限制、全局 token 预算、全局时间预算、子级超时与 token 预算。
- **调度并发执行**。`spawn_agent` 把 `_run` 作为 `asyncio.Task` 调度，随即返回快照，不阻塞调用方。
- **提供选择性等待与事件流**，基于 `asyncio.Condition` 而非轮询。
- **累积模型用量**，从每个 `model.completed` 事件中读取 `Usage` 并累加进 `_tokens_used`。
- **把终端子级输出限定到有界大小**，并填充中性的 `Usage`、artifacts/references 与后代 Thread ID。
- **把协作操作以普通类型化 Tools 的形式注册进参与 Agent 的现有注册表**，从而复用校验、审批、超时、工具结果关联与模型延续路径。
- **支持父/子树取消（最深的子级优先）与恢复（保留 Thread 历史）**。

### 1.2 `WorkflowEngine` 的职责

`WorkflowEngine` 负责确定性工作流的执行：

- **在任何处理器运行前完成结构验证**：端点/身份检查、唯一性检查、Kahn 拓扑排序（DAG 环检测）。
- **按依赖批次调度节点**。只有入站依赖全部到达终止状态、且至少一条入站边「活跃」的节点才进入批次；独立节点在并发信号量约束下成为 `asyncio.Task`。
- **把不活跃的条件分支标记为 `skipped`**，而不是假装它们运行过。
- **在每个稳定批次后序列化一个带版本控制的 `WorkflowRun`**，并交给 `JSONWorkflowStore` 原子地写盘。
- **支持恢复**：保留已完成的 results/state，只重置未完成、失败、跳过或中断的节点。
- **用每 run 单调递增的序号发布事件**，关联工作流/节点生命周期、路由、重试、失败与中断。
- **执行 retry 与 loop 策略**，并把任意处理器异常规范化为 `NodeStatus.FAILED` 与 `WorkflowError`。

### 1.3 混合边界节点的职责

- `AutonomousAgentNode` 把一个 `AgentManager` 的子树当作一个普通工作流节点执行。它**委托给真实的 `AgentManager`**，不模拟模型响应，也不绕过 Tool 执行；等待子级与所有后代，取消残余活动子级，只转发元数据。
- `SubworkflowNode` 把一个嵌套 `Workflow` 当作一个普通节点执行。它派生稳定的子 run ID，优先恢复子级检查点，并把取消级联到子引擎。

### 1.4 `Router` 的职责

`Router` 不拥有任何 provider 或工作流状态。它把一个值加一个不可变上下文视图转换为 `RouteDecision`，观察只包含路由元数据。它服务于工作流的 `NodeKind.ROUTER` 路由场景，也独立可复用。

---

## 2. 数据模型（Data model）

### 2.1 自主编排的数据模型

#### 不可变值类型（对外）

**`AgentStatus`**（`StrEnum`）是 Agent 的公开状态机取值：

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

其中 `PENDING`、`RUNNING`、`WAITING` 属于「活动」状态（模块级常量 `_ACTIVE = frozenset({...})`），`wait` / `wait_all` 依据它判断是否「就绪」。

**`ContextInheritance`**（`StrEnum`）控制上下文继承策略：

```python
class ContextInheritance(StrEnum):
    MINIMAL = "minimal"   # 默认：不继承任何上下文片段
    SELECTED = "selected" # 只继承 selected_sources 指定的来源
    FULL = "full"         # 继承全部片段 + 父级对话历史（以 MEMORY 片段附加）
```

**`MultiAgentLimits`**（frozen dataclass）定义管理器的全局/默认限制：

```python
@dataclass(frozen=True, slots=True)
class MultiAgentLimits:
    max_active_agents: int = 4          # 同时活动的 Agent 上限
    max_total_agents: int = 16          # 树中总 Agent 数上限（不含根）
    max_depth: int = 3                  # 最大深度（根为 0）
    total_token_budget: int = 100_000   # 全局 token 预算
    total_timeout: float = 3_600.0      # 全局时间预算（秒）
    default_agent_timeout: float = 300.0
    max_result_chars: int = 20_000      # 终端结果文本截断上限
```

`__post_init__` 校验：计数/深度/token/字符上限必须为正；两个超时必须为正。违反即抛 `ValueError`。

**`SpawnRequest`**（frozen dataclass）是传给工厂的请求值，工厂据此构造子级 Agent：

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

**`AgentResult`**（frozen dataclass）是终态结果值：

```python
@dataclass(frozen=True, slots=True)
class AgentResult:
    agent_id: str
    status: AgentStatus
    text: str = ""                    # 已截断到 max_result_chars
    artifacts: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    child_trace_ids: tuple[str, ...] = ()  # 后代 Thread ID
```

**`AgentEvent`**（frozen dataclass）是单调递增的事件值，`payload` 被冻结为 `MappingProxyType`：

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

**`AgentSnapshot`**（frozen dataclass）是某个时刻 Agent 的只读视图：

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

#### 可变内部类型（私有）

**`_ManagedAgent`**（非 frozen dataclass）是管理器内部的可变任务记录。它持有对 `Agent` 与 `Thread` 的直接引用、可变的状态字段、`task_handle: asyncio.Task | None` 与 `interrupt_requested: bool`。它的 `snapshot()` 方法把当前状态投影为不可变的 `AgentSnapshot`。**调用方永远接触不到 `_ManagedAgent`**——所有对外操作都返回快照。

### 2.2 工作流的数据模型

#### 结构声明（frozen，构造即校验）

**`NodeKind`**（`StrEnum`）：`FUNCTION`、`TOOL`、`AGENT`、`ROUTER`、`SUBWORKFLOW`、`TRANSFORM`、`GATE`。

**`NodeStatus`**（`StrEnum`）：`PENDING`、`RUNNING`、`COMPLETED`、`FAILED`、`SKIPPED`、`INTERRUPTED`。

**`WorkflowStatus`**（`StrEnum`）：`PENDING`、`RUNNING`、`COMPLETED`、`FAILED`、`INTERRUPTED`。

**`Node`**（frozen dataclass）：

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

`Node.__post_init__` 强制几个关键不变量：
- `node_id` 非空。
- `timeout` 若给定必须为正。
- `max_iterations >= 1`。
- **`loop_until` 为 `None` 时 `max_iterations` 必须等于 1**（否则无谓地多跑）。
- **`retry.max_attempts > 1` 时必须显式声明 `idempotent=True`**——引擎拒绝在未声明幂等性时重试一个节点。

**`Edge`**（frozen dataclass）：

```python
@dataclass(frozen=True, slots=True)
class Edge:
    source: str
    target: str
    route: str | None = None
    predicate: EdgePredicate | None = None
```

`Edge.__post_init__`：两端非空；**`route` 与 `predicate` 不能同时声明**。`conditional` 属性为 `True` 表示该边是条件边（有 `route` 或有 `predicate`）。

**`RetryPolicy`**（frozen dataclass）：

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

`delay` 给出指数退避（封顶于 `max_backoff_seconds`）。

**`NodeOutput`**（frozen dataclass）是处理器可选的结构化返回：

```python
@dataclass(frozen=True, slots=True)
class NodeOutput:
    value: Any = None
    updates: Mapping[str, Any] = field(default_factory=_values)  # 原子地并入 run.state
    route: str | None = None
```

处理器若返回普通值，则 `value` 取该值、`updates` 为空、`route` 为 `None`；返回 `NodeOutput` 则按三个字段解释。

#### 运行时类型

**`WorkflowContext`**（frozen dataclass）是处理器收到的上下文值：

```python
@dataclass(frozen=True, slots=True)
class WorkflowContext:
    workflow_id: str
    run_id: str
    node_id: str
    workflow_input: Any
    state: Mapping[str, Any]          # 当前 run.state 的只读快照
    results: Mapping[str, NodeResult] # 只读的 node_results 视图
    attempt: int
    iteration: int
    emit: Callable[[str, Mapping[str, Any]], Awaitable[None]]  # 节点本地事件发射
```

**`NodeResult`**（可变 dataclass，带 `to_dict`/`from_dict`）：

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

**`WorkflowEvent`**（frozen dataclass，带 `to_dict`/`from_dict`）：`sequence` 是每 run 单调递增的序号（从 1 开始），连同 `workflow_id`、`run_id`、`node_id`、`timestamp`、`payload`。

**`WorkflowState`**（可变 dataclass）：封装 `values: dict`，提供 `update(values)` 与 `snapshot()`（返回 `MappingProxyType`）。

**`WorkflowRun`**（可变 dataclass，可序列化）：

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

`output` 属性返回「最后一个 `COMPLETED` 节点」的 `value`。`to_dict` 写入 `schema_version: 1` 并断言整棵结构可 JSON 序列化（否则抛 `WorkflowError`）；`to_json` 用 `ensure_ascii=False` 序列化。

**`Workflow`**（frozen dataclass，构造即校验）持有 `workflow_id`、`nodes: tuple[Node, ...]`、`edges: tuple[Edge, ...]`。自定义 `__init__` 在构造后立即调用 `self.validate()`。

### 2.3 混合边界的数据模型

- `AutonomousAgentNode` 持有 `manager`、`task: PromptBuilder`、`role`、`parent_agent_id`、`instructions`、`inheritance`、`selected_sources`、`timeout`、`token_budget`，以及一个私有 `_agent_ids: dict[run_id, agent_id]` 用于把工作流 run 关联到被委托的 Agent。
- `SubworkflowNode` 持有 `workflow`、`engine`、`input_builder`、`state_builder`，以及私有 `_active_runs: dict[run_id, child_run_id]`。
- `PromptBuilder = str | Callable[[WorkflowContext], str]`，`InputBuilder = Callable[[WorkflowContext], Any]`，`StateBuilder = Callable[[WorkflowContext], Mapping[str, Any]]`。

### 2.4 路由的数据模型

**`Route`**（frozen dataclass）：`name`、`target`、`predicate: RoutePredicate[T]`、`priority: int = 100`、`metadata`。构造要求 name/target 非空且 predicate 可调用。

**`RouteDecision`**（frozen dataclass）：`route`、`target`、`matched: bool`、`reason`、`timestamp`、`metadata`。

**`Router`**：持有按 `(priority, name)` 排序的 `routes` 元组、`default`、`observer`。

---

## 3. 生命周期（Lifecycle）

### 3.1 `AgentManager` 的生命周期

```
构造 AgentManager
   │  传入 root_agent + factory + limits + hooks + event_listener
   ├─ 生成 root_agent_id = uuid4()
   ├─ 若 expose_tools：把协作 Tools 注册进 root_agent 的注册表
   ├─ 取 root_thread = root_agent.thread()，记录 root_thread_id
   └─ 建立 _agents = {root_agent_id: _ManagedAgent(status=ROOT, depth=0)}

spawn_agent(parent, task, ...)
   ├─ 校验 task/role 非空
   ├─ depth = parent.depth + 1；超限 → MultiAgentError
   ├─ 校验总/活动 Agent 数 → MultiAgentError
   ├─ _check_global_budget()（token/时间）
   ├─ 解析 child_timeout / token_budget 合法性
   ├─ 计算继承上下文（MINIMAL/SELECTED/FULL）
   ├─ factory(request) 构造子级 Agent（失败 → MultiAgentError("child Agent factory failed")）
   ├─ 若 expose_tools：把协作 Tools 注册进子级注册表
   ├─ 建立 _ManagedAgent(PENDING)，登记进 _agents，追加进 parent.child_agent_ids
   ├─ _emit("agent.spawned") + dispatch(SUBAGENT_START)
   │     └─ 若钩子抛错：从 _agents 与 parent.child_agent_ids 移除 → MultiAgentError
   ├─ 把 self._run(child, task) 作为 asyncio.Task 调度
   └─ 返回 child.snapshot()

_run(child, prompt)  [asyncio.Task]
   ├─ status = RUNNING；_emit("agent.started")
   ├─ async with asyncio.timeout(min(child.timeout, 剩余全局秒数)):
   │     遍历 child.thread.astream(prompt)
   │       ├─ _emit_thread_event(...)（默认过滤 model.text/tool_call deltas）
   │       ├─ model.completed → 累加 usage
   │       └─ turn.completed → 记录 response
   ├─ response 为空 → MultiAgentError
   ├─ _tokens_used += usage.total_tokens
   ├─ 判定终态：COMPLETED / BUDGET_EXHAUSTED（子预算或全局预算超限）
   ├─ child.result = _result(...)（截断 text、解析 output_json 的 artifacts/references、填 child_trace_ids）
   ├─ _emit("agent.completed", {result})
   ├─ 异常分支：CancelledError→INTERRUPTED/CANCELLED；TimeoutError→FAILED("agent timed out")；其他→FAILED
   └─ finally：dispatch(SUBAGENT_END)；通知 _completion_condition
        （SUBAGENT_END 钩子失败 → 节点 FAILED，但等待者仍会被通知）

wait / wait_all
   └─ 若目标未就绪：async with _completion_condition: await wait_for(condition.wait_for(ready), timeout)

send_input / resume_agent / interrupt_agent / cancel / close_agent
   └─ 按需改变状态并 _emit 相应事件
```

关键时序点：
- **Spawn 的钩子失败是「先到先得」**：`SUBAGENT_START` 失败会移除待处理的记录（不产生孤儿），并把异常包装为 `MultiAgentError` 抛给调用方。
- **`_run` 是自包含的任务**：无论成功、取消、超时还是异常，`finally` 中都会派发 `SUBAGENT_END` 并 `notify_all` 完成条件，因此等待者绝不会被卡住。
- **interrupt 与 cancel 是两种不同的终止**：`interrupt_agent` 只针对单个活动子级，设置 `interrupt_requested` 后 `task_handle.cancel()`；`cancel` 面向整棵子树，从最深的后代开始逐个 `cancel()`。

### 3.2 `WorkflowEngine` 的执行生命周期

```
run(workflow, workflow_input, *, state, run_id)
   ├─ workflow.validate()                       # 构造已跑过一次，这里再跑
   ├─ 构造 WorkflowRun（PENDING，node_results 全 PENDING）
   └─ _drive(workflow, run, resumed=False)

resume(workflow, checkpoint)
   ├─ 反序列化 checkpoint（str/WorkflowRun/dict）
   ├─ workflow.validate()
   ├─ 校验 checkpoint.workflow_id 与 workflow 一致 → 否则 WorkflowError
   ├─ 校验 checkpoint 节点集 == workflow 节点集 → 否则 WorkflowError
   ├─ 若 checkpoint 已 COMPLETED → 直接返回
   ├─ 把「非 COMPLETED」节点重置为 PENDING（清 error/started/completed）
   ├─ run.status = PENDING；清 error/completed_at
   └─ _drive(workflow, run, resumed=True)

_drive(workflow, run, *, resumed)
   ├─ 注册 cancel_request Event 与 node_tasks 集合
   ├─ run.status = RUNNING；_emit("workflow.resumed"/"workflow.started")；_checkpoint()
   └─ 主循环：
        pending = 所有 status==PENDING 的节点
        若 pending 空 → break
        若 cancel_request 已置位 → _interrupt(run)，返回
        (ready, skipped) = _ready_nodes(...)
           ├─ skipped：标记 SKIPPED、_emit("node.skipped")；若本轮有跳过则 _checkpoint 后 continue
           └─ ready 为空且 pending 非空 → WorkflowError("cannot make progress")
        用 asyncio.Semaphore(max_concurrency) 约束，把每个 ready 节点包成 Task
        await asyncio.gather(*tasks)
           └─ 捕获 CancelledError：若为外部取消则 _interrupt 并 re-raise；否则 _interrupt
        _checkpoint()
        若有 FAILED 节点 → run=FAILED、拼 error、_emit("workflow.failed")、_checkpoint、返回
        循环
   run.status = COMPLETED；_emit("workflow.completed")；_checkpoint；返回
   finally：清理 _cancel_requests / _node_tasks
```

**`_ready_nodes` 就绪判定**：
- 无入站边的节点 → 就绪。
- 任一入站源仍 PENDING/RUNNING → 等待（本批不跑）。
- 任一「无条件」入站源为 FAILED/INTERRUPTED → 本节点 `skipped`。
- 否则计算「活跃边」：`_edge_active` 只对 `COMPLETED` 的源生效，通过 `route` 相等或 `predicate` 求值判断。活跃边存在 → 就绪；否则 → `skipped`。

**`_execute_node`（单个节点，含 loop 与 retry）**：
- `result.status = RUNNING`、`started_at`、`_emit("node.started")`。
- 外层 `for iteration in 1..max_iterations`：每次 `_invoke_with_retry`，归一化输出，`run.state.update(updates)`，记录 `last_value`/`last_route`；若 `loop_until` 满足则 `break`；循环耗尽仍未满足 → `WorkflowError("reached its max loop iterations")`。
- 若该节点声明了出边 `route`，校验所选 route 属于声明集合，否则 `WorkflowError("selected unknown route")`。
- 写回 `result.value/route/status=COMPLETED/completed_at`；`_emit("route.selected")`、`_emit("node.completed")`。
- 异常：`CancelledError` → `INTERRUPTED` 并 re-raise；其他 → `FAILED`（`_emit("node.failed")`）。

**`_invoke_with_retry`（单个 attempt）**：循环 `1..retry.max_attempts`，递增 `result.attempts`，构造 `WorkflowContext`，调用 `node.handler(context)`；若可等待则 `await`，且 `node.timeout` 非空时用 `asyncio.wait_for` 包裹。`CancelledError` 直接 re-raise；其他异常若未到上限则 `_emit("node.retrying")` 并按 `delay` 退避后重试。

### 3.3 混合节点生命周期

**`AutonomousAgentNode.__call__`**：
1. 解析 `task`（`PromptBuilder` 若可调用则求值）；为空 → `WorkflowError`。
2. 记录 `cursor = max(event_history().sequence)`（用于只转发本次新增事件）。
3. `manager.spawn_agent(...)` 生成子级，把 `run_id → agent_id` 记入 `_agent_ids`。
4. `wait_all([child.agent_id])` 等子级；再 `wait_all(descendants)` 等所有后代。
5. 若仍有活动快照 → `manager.cancel(child)` 取消残余子树。
6. `_forward_agent_events` 只转发该子树相关的元数据事件。
7. 若子级非 `COMPLETED` 或 `result is None` → `WorkflowError`。
8. 若存在失败的后代 → `WorkflowError`。
9. 返回 `NodeOutput(result.text, {hybrid.<node>.agent_id/thread_id/tokens})`。
10. 捕获 `CancelledError` → `manager.cancel(child)`、转发事件、re-raise。

**`SubworkflowNode.__call__`**：
1. `child_run_id = _child_run_id(parent_run_id, node_id)`（`<parent-run>-<safe-node>`）。
2. 尝试 `_load_if_present(engine.store, child_run_id)`。
3. 有检查点 → `engine.resume(workflow, checkpoint)`；否则 `engine.run(workflow, input_builder(context), state=state_builder?(context), run_id=child_run_id)`。
4. `_forward_subworkflow_events(context, child, after_sequence=len(checkpoint.events) if 有)`。
5. 非 `COMPLETED` → `WorkflowError`。
6. 返回 `NodeOutput(child.output, {hybrid.<node>.workflow_id/run_id})`。
7. 捕获 `CancelledError` → `engine.cancel(child_run_id)`、转发最新检查点事件、re-raise。

### 3.4 `Router` 生命周期

`aroute(value, *, context)` 依序求值每个 `route.predicate(value, safe_context)`（支持异步谓词），命中即构造 `RouteDecision(matched=True)` 并 `_observe` 返回；全未命中则用 `default`（无默认则 `WorkflowError`）。`route(...)` 是同步封装：无事件循环时用 `asyncio.run`；在活动事件循环内调用则抛 `RuntimeError`，要求改用 `aroute`。

---

## 4. 关键接口/类（Key interfaces/classes）

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

`events()` 是一个基于 `_event_condition` 的异步生成器：先把游标之后已有的事件 `yield` 完，再 `await` 条件变量等待新事件。这是「事件流而非轮询」的对外形态。

### 4.2 协作 Tools

`collaboration_tools(parent_agent_id)` 返回六个普通 `@tool` 装饰的类型化 Tools（`source="multi_agent"`，`risk="runtime"`）：

| Tool 名 | 签名 | 语义 |
|---|---|---|
| `spawn_agent` | `(task, role="worker", instructions=None, inheritance="minimal", selected_sources=None, timeout=None, token_budget=None) -> AgentSnapshot` | 在指定父级下派生子级并并发启动 |
| `send_input` | `(agent_id, message) -> AgentSnapshot` | 发送转向或排队后续输入 |
| `wait_agent` | `(agent_ids=None, timeout=30.0) -> list[dict]` | 等待至少一个选中子级进入终态 |
| `resume_agent` | `(agent_id, message=None) -> AgentSnapshot` | 用排队/显式输入恢复非活动子级 |
| `interrupt_agent` | `(agent_id) -> AgentSnapshot` | 中断单个活动子级，不取消父级 |
| `close_agent` | `(agent_id) -> AgentSnapshot` | 关闭子树但保留可恢复状态 |

这些工具被 `_attach_tools` 注册进 root 与每个子级 Agent 的 `tool_registry`。冲突（`ToolError`）被包装为 `MultiAgentError("Agent has a conflicting collaboration tool")`。

### 4.3 工作流

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

### 4.4 混合边界工厂

```python
agent_node(node_id: str, manager: AgentManager, task: PromptBuilder, *,
           role: str = "worker", parent_agent_id: str | None = None,
           instructions: str | None = None,
           inheritance: ContextInheritance = ContextInheritance.MINIMAL,
           selected_sources: Sequence[str] = (),
           timeout: float | None = None, token_budget: int | None = None) -> Node
# 返回 Node(node_id, AutonomousAgentNode(...), NodeKind.AGENT, timeout=timeout)

subworkflow_node(node_id: str, workflow: Workflow, *,
                 engine: WorkflowEngine | None = None,
                 input_builder: InputBuilder = _input,
                 state_builder: StateBuilder | None = None) -> Node
# 返回 Node(node_id, SubworkflowNode(...), NodeKind.SUBWORKFLOW)
```

### 4.5 路由

```python
Route[T](name: str, target: str, predicate: RoutePredicate[T],
         priority: int = 100, metadata: Mapping[str, Any] = ...)
Router[T](routes: Sequence[Route[T]], *, default: str | None = None,
          observer: EventObserver | None = None)
    async def aroute(self, value: T, *, context: Mapping[str, Any] | None = None) -> RouteDecision
    def route(self, value: T, *, context: Mapping[str, Any] | None = None) -> RouteDecision
```

---

## 5. 并发与取消（Concurrency / cancellation）

### 5.1 `AgentManager` 的并发模型

- **每个子级一个 `asyncio.Task`**。`spawn_agent` 返回前已 `create_task`，因此子级立即开始并发执行；调用方拿到的是立即返回的快照。
- **活动数限制**由 `_active_count()`（统计 `_ACTIVE` 状态）在 spawn 与 resume 时校验。
- **等待基于 Condition 而非轮询**。`wait`/`wait_all` 用 `_completion_condition`；`_run` 结束时在 `finally` 中 `notify_all`。没有 busy-poll 循环。
- **事件流基于 Condition**。`events()` 用 `_event_condition`，`_emit` 在追加事件后 `notify_all`。

#### 取消语义

- **`interrupt_agent(agent_id)`**：只针对单个活动子级。置 `interrupt_requested=True` 后 `task_handle.cancel()`，并 `await _await_cancelled(task_handle)`（吞掉 `CancelledError`）。结果状态为 `INTERRUPTED`。
- **`cancel(agent_id=None)`**：面向子树。`_subtree` 返回包含目标及其所有后代的列表，**按 reversed 顺序（最深的子级优先）逐个 `cancel()`**，再 `asyncio.gather(..., return_exceptions=True)` 等待全部收尾。这保证取消先作用于叶节点，避免父级先取消后子级悬挂。
- **`close_agent`**：先 `cancel` 子树，再把子树中每个节点置 `CLOSED`、记录 `completed_at`、`await thread.aclose()`、`_emit("agent.closed")`。
- **`aclose`**：`cancel()` 全部，然后关闭所有 thread 与 agent。
- 在 `_run` 中捕获 `CancelledError` 时，按 `interrupt_requested` 区分 `INTERRUPTED` 与 `CANCELLED`。

### 5.2 `WorkflowEngine` 的并发模型

- **依赖就绪的节点按批执行**。`_drive` 主循环每一轮计算一批 `ready` 节点。
- **`asyncio.Semaphore(max_concurrency)`**（默认 8）限制同批内并发执行节点数。
- **join 就绪条件**：一个节点的所有入站源都到达终止状态（无 PENDING/RUNNING）且至少一条入站边活跃。`test_parallel_nodes_overlap_then_join` 验证三个分支并发峰值为 `max_concurrency`，join 汇总三路结果。
- **loop 是节点本地的**：并发与图的环无关，环在 `validate` 阶段就被拒绝。

#### 取消语义

- **`cancel(run_id)`**：置位对应 run 的 `cancel_request` Event，并逐个 `cancel()` 该 run 的 `_node_tasks`。返回该 run 是否被注册。
- **`_drive` 内的取消**：若 `cancel_request` 已置位则 `_interrupt(run)` 并返回；若 `gather` 捕获 `CancelledError` 且非显式取消则也先 `_interrupt` 再 `re-raise`（这样调用方任务被取消时，检查点已持久化为 `INTERRUPTED`）。
- **`_interrupt`**：把仍 `RUNNING` 的节点置 `INTERRUPTED`，run 置 `INTERRUPTED`，`_emit("workflow.interrupted")`，`_checkpoint`。
- **节点取消**：`_execute_node` 捕获 `CancelledError` 时把该节点置 `INTERRUPTED` 并 re-raise，由上层统一处理。
- **retry 中的取消**：`_invoke_with_retry` 对 `CancelledError` 直接 re-raise，不进入退避重试。

### 5.3 混合边界的取消级联

- `AutonomousAgentNode.cancel(run_id)` 通过 `_agent_ids` 找到被委托的子级并 `manager.cancel(agent_id)`，把工作流取消传入 Agent 子树。`__call__` 的 `CancelledError` 分支同样先取消子树再转发事件。
- `SubworkflowNode.cancel(run_id)` 通过 `_active_runs` 找到子 run 并 `engine.cancel(child_run_id)`。取消跨两个引擎传播：子引擎先把自己的检查点写成 `INTERRUPTED`，父引擎随后记录父节点的 `INTERRUPTED`。

---

## 6. 持久化（Persistence）

### 6.1 `AgentManager` 的持久化边界

`AgentManager` 本身**不直接写盘**。它的持久化载体是每个子级独立的 `Thread`（`SQLiteThreadStore` 提供的持久化历史）。Resume 保留同一 Thread 历史：`resume_agent` 重新调度 `_run`，用排队消息组成提示继续跑同一 Thread，因此 `turn_count` 递增、上下文与历史得以延续。跨进程的状态恢复则随「持久化扩展」加入（详见持久化章节）。

### 6.2 `WorkflowEngine` 的持久化

- **`WorkflowRun.to_dict/to_json`** 是带版本控制的完整序列化：`schema_version: 1` + `workflow_id` + `run_id` + `workflow_input` + `state` + `node_results` + `status` + `events` + 时间戳 + `error`。`to_json` 前 `_assert_json_serializable` 会拒绝任何不可序列化的状态值（抛 `WorkflowError`）。
- **`JSONWorkflowStore`** 按 `run_id` 落盘，使用**原子替换**：

```python
def save(self, run: WorkflowRun) -> Path:
    path = self._path(run.run_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(run.to_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return path
```

先写 `run_id.json.tmp`，再 `replace` 成 `run_id.json`，避免写一半读到损坏检查点。
- **`_path` 白名单**：`run_id` 只允许字母、数字、`-`、`_`，杜绝路径穿越（`test_checkpoint_rejects_non_json_state_and_path_traversal` 验证 `"../escape"` 被拒绝）。
- **检查点时机**：`_drive` 在 `workflow.started/resumed` 后、每个稳定批次后、以及失败/中断/完成时都会 `_checkpoint`。store 为 `None` 时不写盘（内存模式）。

### 6.3 恢复语义

`resume` 的核心规则：
- **已完成的节点被保留**：`COMPLETED` 节点的 `value`/`state` 不被重置，处理器不再重跑。
- **未完成/失败/跳过/中断的节点被重置为 PENDING**，并清空 `error`/`started_at`/`completed_at`。
- **run 级重置**：`status=PENDING`、清 `error`、`completed_at`。
- 校验 checkpoint 与 workflow 的 `workflow_id` 与节点集合完全一致，否则抛 `WorkflowError`。
- 已 `COMPLETED` 的 run 直接返回，不重跑。

`test_failure_checkpoint_can_resume_without_replaying_completed_nodes` 验证：失败后恢复时 `first` 只调用一次、`second` 调用两次、state 保留 `{"saved": True}`。

### 6.4 混合边界的持久化

- `SubworkflowNode` 复用子级 `JSONWorkflowStore`：重复的父节点会 `resume` 该检查点，只转发比已加载快照更新的事件序列（`after_sequence = len(checkpoint.events)`）。
- `AutonomousAgentNode` 的事件游标同样只转发 `after_sequence=cursor` 的新增事件。

---

## 7. 事件与可观测性（Events / observability）

### 7.1 `AgentManager` 事件

`AgentEvent` 的 `sequence` 在管理器内**单调递增**（`self._sequence += 1`）。事件类型包括：

| 事件 | 触发点 |
|---|---|
| `agent.spawned` | spawn 成功登记后（含 role/depth） |
| `agent.started` | `_run` 进入 RUNNING |
| `agent.event` | 子级 Thread 事件转发（默认过滤 `model.text.delta` / `model.tool_call.delta`） |
| `agent.message` | `send_input` |
| `agent.resumed` | `resume_agent` |
| `agent.completed` | 正常完成（含 result） |
| `agent.failed` | 超时/异常/SUBAGENT_END 钩子失败 |
| `agent.interrupted` / `agent.cancelled` / `agent.budget_exhausted` | 对应终态 |
| `agent.closed` | `close_agent` |

消费方式：
- `event_history(after_sequence=0)` 拉取历史。
- `events(after_sequence=0)` 拉取历史并持续等待新事件（异步生成器）。
- `event_listener` 回调在 `_emit` 内被同步调用，返回值若可等待则被 `await`。
- **`include_child_deltas=False`（默认）会过滤子级文本/token 增量**，父级只收到有界结果与聚合生命周期事件。协作 Tools 的 `wait_agent` 返回 `asdict(snapshot)` 列表。

### 7.2 `WorkflowEngine` 事件

`WorkflowEvent.sequence` 每 run 从 1 递增（`len(run.events) + 1`），并关联 `workflow_id`/`run_id`/`node_id`。类型包括：`workflow.started`、`workflow.resumed`、`workflow.completed`、`workflow.failed`、`workflow.interrupted`、`node.started`、`node.completed`、`node.failed`、`node.skipped`、`node.interrupted`、`node.retrying`、`route.selected`。`event_listener` 回调同样支持同步/异步。`WorkflowContext.emit` 让处理器发射节点本地事件，全部写回同一个 `run.events`。

### 7.3 混合边界事件桥接

- **Agent → 工作流**：`_forward_agent_events` 只转发相关子树的事件，`payload` 含 `source="autonomous_agent"`、`agent_sequence`、`agent_id`、`parent_agent_id`，但**省略子级文本/token 负载体**（只转发 ID 与生命周期类型）。桥接事件的 `node_id` 被设为其所属工作流节点。
- **子工作流 → 工作流**：`_forward_subworkflow_events` 把子 run 事件以 `subworkflow.<type>` 前缀转发，`payload` 含 `source="subworkflow"`、`child_workflow_id`、`child_run_id`、`child_sequence`、`child_node_id`，并受 `after_sequence` 过滤。

### 7.4 `Router` 观测

`Router` 通过 `observer: EventObserver` 发射 `Event("route.selected", payload={route, target, matched, reason, metadata})`（`_observe`），支持同步/异步 observer，且只包含路由元数据，不含被路由的值本身。

---

## 8. Codex 参考（Codex reference）

本设计基于对 Codex 源码与测试的逆向研究，详细记录见 `docs/research/codex/`：

- **自主多 Agent**：`docs/research/codex/autonomous-multi-agent.md`。逆向自 `codex-rs/core/src/session/multi_agents.rs`、`tools/handlers/multi_agents_common.rs`、`multi_agents/spawn.rs`、`send_input.rs`、`wait.rs`、`resume_agent.rs`、`close_agent.rs`、`multi_agents_v2/interrupt_agent.rs` 及对应测试。行为契约：模型可调用 spawn/message/wait/resume/interrupt/close，子级并发、可再派生、独立线程与配置、只继承被请求的上下文、报告有界终态；wait 是选择性与事件驱动的；取消/关闭级联子树。
- **确定性工作流**：`docs/research/codex/deterministic-workflow.md`。逆向自 `codex-rs/protocol/src/plan_tool.rs`、`core/src/tools/handlers/plan.rs`、`plan_spec.rs`、`session/turn.rs`、`base_instructions/default.md`。结论：Codex 的 `update_plan` 是一个 checklist 而非可执行图；Super Harness 采纳其「严格解析、显式状态转换、事件发布」的契约，但扩展成真正的可执行 DAG 引擎。
- **混合编排**：`docs/research/codex/hybrid-orchestration.md`。综合上述两者：复用自治 Agent 生命周期，把计划面从「checklist」升格为「可执行工作流」，并在二者之间建立桥接。

---

## 9. Python 原生重设计（Python-native redesign）

- **Rust 协议枚举与服务依赖被替换为 Python dataclass 值**。`AgentStatus`/`NodeStatus`/`WorkflowStatus` 是 `StrEnum`；`AgentSnapshot`/`AgentResult`/`AgentEvent`/`WorkflowRun`/`NodeResult`/`WorkflowEvent` 是不可变或带序列化的 dataclass。没有 Codex 的 `SessionSource`、`EventMsg::PlanUpdate`、`ModeKind` 等。
- **协作不依赖专属服务**。Codex 的协作绑定 Rust session 服务；Super Harness 把协作操作做成普通 `@tool`，注册进既有 `ToolRegistry`，因此自动复用校验、审批、超时、工具结果关联与模型延续。
- **工作流引擎不需要模型 provider**。`WorkflowEngine` 只运行 Python 处理器；节点可以调用任意应用函数。`WorkflowContext` 是 provider 无关的 Python 值。
- **序列化是 JSON 而非协议编码**。`WorkflowRun`/`WorkflowEvent`/`NodeResult` 提供 `to_dict`/`from_dict`，检查点用 `json.dumps(..., ensure_ascii=False)`，原子写盘。
- **并发用 `asyncio` 原语**：`asyncio.Task`、`asyncio.Condition`、`asyncio.Semaphore`、`asyncio.Event`、`asyncio.timeout`，没有自研线程池或轮询器。

---

## 10. 有意差异（Intentional differences）

- **wait 用 Condition 而非轮询**：Codex 的 wait 语义被重做为 `asyncio.Condition.wait_for(ready)`，事件流同样基于 Condition。
- **`_ManagedAgent` 私有、快照公开**：对外永远是不可变快照，杜绝调用方在运行中改写状态。
- **默认隐藏子级 deltas**：`include_child_deltas=False` 时父级不收到 `model.text.delta`/`model.tool_call.delta`，避免父级被子级 token 流淹没。
- **重试必须显式声明幂等性**：这是与「无脑重试」的刻意差异。`Node` 构造在 `retry.max_attempts>1` 而 `idempotent=False` 时直接抛 `ValueError`。
- **loop 是节点本地且必须有限**：图的回边被 `validate` 拒绝；循环只能存在于单节点内部且必须有 `max_iterations` 上限与 `loop_until` 谓词。
- **不活跃分支标记为 `skipped` 而非「假装成功」**：这样选中的分支可以重新汇合，同时不虚报未运行处理器的结果。
- **`Router.route` 在活动事件循环内禁止调用**：强制使用 `aroute`，避免在循环内隐式 `asyncio.run` 引发 `RuntimeError`。

---

## 11. 失败模型（Failure model）

### 11.1 自主编排

- **`MultiAgentError`**（继承 `SuperHarnessError`）用于所有编排契约/限制违反：
  - 空 task/role、未知 agent、操作要求 child、恢复活动中的 agent、无输入的恢复。
  - 深度/总 Agent 数/活动 Agent 数超限、token 预算耗尽、时间预算耗尽。
  - `SUBAGENT_START` 钩子失败（先移除待处理记录再抛）、协作 Tool 冲突。
- **子级终态**：超时 → `AgentStatus.FAILED`（error `"agent timed out"`）；处理器/流异常 → `FAILED`（error 为 `TypeError: msg` 形式）；`CancelledError` → `INTERRUPTED`（若 `interrupt_requested`）或 `CANCELLED`；预算超限 → `BUDGET_EXHAUSTED`。
- **`SUBAGENT_END` 钩子失败**：把节点置 `FAILED` 并记录 `"subagent end hook failed: ..."`，但**仍通知等待者**——等待绝不会因钩子失败而挂起。
- **超时**：`asyncio.timeout(min(child.timeout, 剩余全局秒数))`。子级超时与全局时间预算都生效，取较小者。

### 11.2 工作流

- **`WorkflowError`**（继承 `SuperHarnessError`）用于结构/运行时错误：空 workflow_id、空节点集、重复节点、边引用未知节点、自环、图环、不可推进的检查点、未知 route、超限 loop、不可序列化状态、非法 run ID、checkpoint 不匹配。
- **节点失败**：任何处理器异常被 `_execute_node` 捕获并规范化为 `NodeResult.status = FAILED`、`error = f"{TypeError.__name__}: {msg}"`、`_emit("node.failed")`。批次结束后，任何 `FAILED` 节点使整个 run 置 `WorkflowStatus.FAILED`（`error` 拼接各失败节点）。
- **超时**：`node.timeout` 经 `asyncio.wait_for` 生效，`TimeoutError` 被当作节点失败（`test_timeout_is_normalized_as_node_failure` 验证 `"TimeoutError"` 出现在 run.error）。
- **重试**：`_invoke_with_retry` 在未达 `max_attempts` 时按 `RetryPolicy.delay` 退避重试，`CancelledError` 不重试。
- **中断**：取消产生 `INTERRUPTED`（节点与 run 级），检查点同步写盘，可随后恢复。

### 11.3 混合边界

- `AutonomousAgentNode`：子级或任何后代非 `COMPLETED` → `WorkflowError("autonomous agent node failed: ...")` / `"autonomous agent descendant failed: ..."`；空任务 → `WorkflowError`。
- `SubworkflowNode`：子 run 非 `COMPLETED` → `WorkflowError(f"subworkflow failed: {error or status}")`。
- 取消沿两层传播：父 `WorkflowEngine.cancel` → `SubworkflowNode.cancel` → 子 `WorkflowEngine.cancel`；父取消 → `AutonomousAgentNode.cancel` → `AgentManager.cancel`。

---

## 12. 扩展点（Extension points）

- **`AgentFactory`（`Callable[[SpawnRequest], Agent]`）**：这是自主编排最主要的扩展点。工厂决定每个子级用什么 provider、指令与上下文。典型实现见 `examples/43_autonomous_research.py`：用 `request.instructions` 与 `request.inherited_context` 构造子级。
- **`HookRegistry` + `HookEvent.SUBAGENT_START`/`SUBAGENT_END`**：在子级启动/结束时插入审计、日志或护栏。
- **`event_listener` / `events()`**：接入自定义事件消费（如流式 UI、追踪）。
- **`include_child_deltas` / `expose_tools`**：开关决定父级是否收到子级 token 流、以及是否把协作 Tools 暴露给 Agent。
- **`MultiAgentLimits`**：覆盖全局并发/预算策略。
- **`WorkflowEngine(max_concurrency, store, event_listener)`**：并发度、持久化与事件三者均可替换。
- **`JSONWorkflowStore`**：可替换为其他后端（实现 `save`/`load`）。
- **`NodeKind` + 工厂**：`agent_node`/`subworkflow_node` 是现成的节点工厂；可新增自定义 `NodeKind`。
- **`Router` 与 `Route`**：predicate 支持同步/异步，可用于任何「按值路由」的场景。
- **`input_builder` / `state_builder`**：`SubworkflowNode` 的子工作流入参/初始状态可从父上下文动态构造。

---

## 13. 测试（Tests）

对应测试文件（`tests/`）：

- **`tests/test_autonomous.py`**：
  - `test_spawn_three_concurrently_selective_wait_aggregate_and_trace_tree`：并发 spawn、选择性 wait、聚合结果、事件单调序列、默认过滤子级 deltas。
  - `test_model_autonomously_spawns_waits_and_aggregates_via_tools`：模型通过 `spawn_agent`/`wait_agent` 工具自主编排。
  - `test_send_resume_close_and_structured_result`：send/resume/close 生命周期与 turn 计数。
  - `test_interrupt_and_parent_cancel_propagate_to_subtree`：interrupt 单点、cancel 级联到子树。
  - `test_depth_active_total_timeout_failure_and_budget_guards`：全部限制与预算护栏。
  - `test_context_inheritance_and_subagent_hooks`：三种继承策略与 SUBAGENT_START/END 钩子计数。
  - `test_subagent_hook_failure_does_not_orphan_or_block_wait`：START 钩子失败不产生孤儿、END 钩子失败不阻塞等待。
- **`tests/test_workflow.py`**：
  - 顺序传参/状态、并行 join 峰值、条件路由跳过、router 事件、未知 route 失败、重试退避与幂等契约、loop 终止与严格护栏、DAG 校验（未知节点/重复/环）、失败检查点恢复不重放、公开取消中断与检查点恢复、调用方取消持久化中断、超时规范化为失败、predicate 边与异步 listener、检查点拒绝非 JSON 状态与路径穿越。
- **`tests/test_hybrid.py`**：
  - Agent 节点跑在序列内并桥接事件、子工作流返回输出/状态/关联事件、工作流 Agent 自主调用专家团队、工作流取消级联进 Agent 子树、父取消中断并检查点子工作流、失败子工作流恢复稳定子检查点。
- **`tests/test_autonomous_e2e.py`**：端到端路径。

---

## 14. 限制与未来工作（Limitations / future work）

- **`AgentManager` 不直接提供跨进程状态持久化**；当前跨进程恢复依赖 `Thread` 的持久化（`SQLiteThreadStore`）与「持久化扩展」的演进。
- **工作流图不支持回边**；循环被刻意限制为节点本地且必须有严格上限。更复杂的图型（如嵌套/动态生成图）不在当前 `validate` 范围。
- **`WorkflowRun` 检查点是整批快照**：在极大图上每批次全量序列化会有 IO 成本；未来可考虑增量/分片检查点。
- **`AutonomousAgentNode` 的有界等待依赖 `timeout`**：若子级及其后代在 timeout 内未收敛，节点会取消残余子树并失败——这是刻意的安全网，但也意味着长尾任务可能被切断。
- **路由 `Router` 是线性求值**（按 priority/name 排序遍历），对于海量路由缺乏索引/分片。
- **子级上下文继承的 `FULL` 模式会把父级全部历史拼成一条 `MEMORY` 片段**，在历史很长时可能放大 token 开销。

---

## 相关链接

- 可运行示例：`examples/43_autonomous_research.py`、`examples/47_agent_budget_cancel.py`、`examples/48_workflow_sequence.py`、`examples/49_workflow_parallel.py`、`examples/50_workflow_conditional.py`、`examples/51_workflow_router.py`、`examples/52_workflow_retry_loop.py`、`examples/53_hybrid_agent_node.py`、`examples/54_hybrid_subworkflow.py`、`examples/55_hybrid_specialist_team.py`、`examples/56_hybrid_failure_resume.py`
- Codex 参考：`docs/research/codex/autonomous-multi-agent.md`、`docs/research/codex/deterministic-workflow.md`、`docs/research/codex/hybrid-orchestration.md`
- 源码：`src/super_harness/orchestration/`（`autonomous.py`、`workflow.py`、`hybrid.py`、`router.py`）
