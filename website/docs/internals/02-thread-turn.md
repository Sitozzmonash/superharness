---
id: internals-thread-turn
title: Thread / Turn 模型与运行时
sidebar_position: 2
description: Thread/Turn 生命周期、事件模型、流式内部机制、上下文片段、压缩与取消/转向的运行时实现原理。
---

# Thread / Turn 模型与运行时

> 本文回答“运行时内部如何工作、为何这样设计”。对应的“怎么用”见用户指南页；本页专注原理，不写操作教程。
> 相关研究证据见 `docs/research/codex/agent-runtime-thread-turn.md`、`docs/research/codex/durable-thread-context-compaction.md`、`docs/research/codex/model-provider-and-streaming.md`，以及镜像 `references/codex/` 下的对应文件。

## 1. 职责（Responsibilities）

运行时（`super_harness/runtime/`）把“一次对话”拆成两个层次：**Thread** 与 **Turn**。二者分工如下：

- **Thread（线程 / 会话）** 拥有一个 Agent 会话的有序历史：消息列表、Turn 列表、上下文片段、摘要（summaries）、压缩阈值、工具注册表与执行器、Hook 与事件观察者，以及可选的持久化存储。它是“状态的容器”，本身不发起模型调用，只编排。
- **Turn（回合）** 代表“一次用户发起的执行”及其终止诊断：输入、状态机、时间戳、最终响应、错误信息。它是“单次执行的记录”。
- **事件（Event）** 是不可变的结构化观察值，用于把生命周期暴露给下游，而无需客户端窥探内部状态。
- **TurnHandle** 是活动 Turn 的事件与控制句柄：消费同一条权威事件流，并支持 `steer`（转向）、`cancel`（取消）、`interrupt`（中断）。

核心不变量：

1. 历史顺序稳定、在基本内存运行期间是 append-only 的。
2. 每个 Turn 恰好记录一个终止状态（completed / failed / interrupted / cancelled）。
3. 失败或取消的 Turn 保留诊断状态（`error` 字段与时间戳），不静默消失。
4. 模型增量事件先于 `model.completed` 事件；Turn 只有在 provider 完成之后才完成。
5. 流式路径是权威路径：非流式收集（`run`/`arun`）只是流式 API 的薄消费者。
6. 公共同步包装（`stream`/`run`）不得嵌套事件循环。

运行时依赖精简的 `ModelProvider` 协议，绝不依赖 provider SDK 的响应类；Thread 与 Turn 存储 provider 中性的消息与模型结果，不保存 Responses API 对象、OpenAI item 变体、账户元数据或传输会话状态。

## 2. 数据模型（Data model）

### 2.1 TurnStatus —— 状态枚举

`super_harness/runtime/turn.py` 定义 `TurnStatus`（`StrEnum`），共七个状态，其中四个是终止状态：

```python
class TurnStatus(StrEnum):
    PENDING = "pending"          # 已创建，尚未 start()
    RUNNING = "running"          # 已开始，正在执行模型/工具编排
    WAITING_TOOL = "waiting_tool"  # 已收到工具调用，等待工具结果返回
    COMPLETED = "completed"      # 终止：正常完成，有最终 ModelResponse
    FAILED = "failed"            # 终止：抛出异常
    INTERRUPTED = "interrupted"  # 终止：被显式中断（interrupt / 流提前关闭 / 恢复前的挂起 Turn）
    CANCELLED = "cancelled"      # 终止：被取消（cancel）
```

状态迁移约束在 `Turn` 的方法里强制：
- `start()`：只有 `PENDING` 可以开始 → 置为 `RUNNING`，记录 `started_at`。
- `complete(response)`：只有 `RUNNING` 或 `WAITING_TOOL` 可以完成 → 置为 `COMPLETED`，记录响应与 `completed_at`。
- `fail(error)`：置为 `FAILED`，记录 `error` 与 `completed_at`。
- `cancel()`：置为 `CANCELLED`，记录 `completed_at`。

### 2.2 Turn —— 回合值

```python
@dataclass(slots=True)
class Turn:
    input: str
    turn_id: str = field(default_factory=lambda: str(uuid4()))
    status: TurnStatus = TurnStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    response: ModelResponse | None = None
    error: str | None = None
```

`Turn` 用 UTC 时间戳（`datetime.now(UTC)`），`response` 是 provider 中性的 `ModelResponse`，`error` 是字符串诊断。

### 2.3 Event —— 不可变事件

`super_harness/runtime/events.py` 定义冻结事件。所有关联字段都是可选的，因此同一个基类可以表示 thread、turn、tool、subagent、workflow 事件：

```python
@dataclass(frozen=True, slots=True)
class Event:
    type: str
    event_id: str = field(default_factory=_new_event_id)   # uuid4
    timestamp: datetime = field(default_factory=_utc_now)  # datetime.now(UTC)
    thread_id: str | None = None
    turn_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    workflow_run_id: str | None = None
    node_id: str | None = None
    tool_call_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=_empty_payload)
```

`__post_init__` 的三条校验/固化规则：
1. `type` 必须是非空字符串。
2. `timestamp` 必须带时区（tz-aware），否则拒绝。
3. `payload` 会被防御性拷贝，并暴露为 `MappingProxyType` 的只读映射——调用方无法篡改载荷。

观察边界 `EventObserver` 是最小协议，同步/异步兼容：

```python
class EventObserver(Protocol):
    def observe(self, event: object) -> object: ...
```

### 2.4 关联的消息与模型值

- `Message`（`super_harness/models/types.py`，frozen）：`role`、`content`、`name`、`tool_call_id`、`tool_calls`（`tuple[ToolCall, ...]`）。
- `MessageRole`：`system` / `developer` / `user` / `assistant` / `tool`。
- `ModelRequest`：`messages`、`tools`、`output_schema`、`temperature`、`parallel_tool_calls`、`extra`。
- `ModelResponse`：`text`、`tool_calls`、`usage`（`Usage`）、`response_id`、`finish_reason`、`output_json`。
- `ModelStreamEventType`：`started` / `text_delta` / `tool_call_delta` / `completed`。
- `ModelStreamEvent`：`type`、`delta`、`tool_call_index`、`tool_call_id`、`tool_name`、`response`。

这些值全部 frozen，跨 provider 边界保持中性。

### 2.5 上下文片段与摘要

- `ContextKind`：`runtime` / `developer` / `project` / `persona` / `skill` / `memory` / `rag` / `summary`。
- `ContextPriority`（`IntEnum`，值越大权威越低）：`RUNTIME=10`、`DEVELOPER=20`、`PROJECT=40`、`PERSONA=50`、`SKILL=60`、`SUMMARY=70`、`MEMORY=80`、`RAG=90`。
- `ContextFragment`：`kind`、`content`、`source`、`role`（默认 `USER`）、`priority`、`metadata`。`effective_priority` 返回显式优先级或按 `kind` 推断的默认值；`render()` 把它包装成 `<context kind="..." source="...">…</context>` 的用户角色消息。
- `ContextSummary`：`content`、`summarized_messages`、`summary_id`、`created_at`。

## 3. 生命周期（Lifecycle）

### 3.1 Turn 生命周期（ASCII）

一次 Turn 的生命周期与终止状态：

```
                     ┌────────────────────────────────────────────┐
                     │            TurnStatus 状态机                │
                     └────────────────────────────────────────────┘

  start()                      模型步循环
  ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐
  │ PENDING  │──▶│ RUNNING  │──▶│ WAITING_TOOL │──▶│ RUNNING  │ ...
  └──────────┘   └──────────┘   └──────────────┘   └──────────┘
                    │   │                              │
                    │   │  complete(response)          │  complete(response)
                    │   └──────────────▶┌──────────┐   └────────▶┌────────────┐
                    │                   │ COMPLETED │             │ (终态)      │
                    │                   └──────────┘             └────────────┘
                    │
                    │  fail(exc)   ┌────────┐
                    └────────────▶│ FAILED │   (终止，保留 error)
                                 └────────┘

  取消路径：
     cancel()            ┌───────────┐
      ────────────────▶  │ CANCELLED │  (终止，独立于中断)
                         └───────────┘
  中断路径：
     interrupt() / 流提前关闭 / 恢复前的挂起 Turn
                         ┌─────────────┐
      ────────────────▶  │ INTERRUPTED │  (终止，独立于取消)
                         └─────────────┘
```

`WAITING_TOOL` 是“非终止”的中间状态：收到工具调用后置位，工具结果回填后回到 `RUNNING`，继续下一模型步。它不终止 Turn，只有 `completed / failed / interrupted / cancelled` 四个终态。

### 3.2 Turn 执行时序（一次完整流式 Turn）

```
Thread.astream(input)
  │
  ├─ 前置守卫：archived? / active_turn_id? / 空输入?
  ├─ SESSION_START hook（仅首次）、USER_PROMPT hook（可改写/拒绝输入）
  ├─ 创建 Turn(PENDING) → self._active_turn_id = turn.turn_id
  ├─ 追加 Message(USER, input) → turn.start() → RUNNING
  ├─ TURN_START hook
  ├─ _persist()                       # 持久化快照
  ├─ yield turn.started
  ├─ 若历史超阈值 → acompact()（见 §6）
  │
  └─ for step in 1..max_model_steps:
       ├─ 排空 _steering_by_turn[turn] → 追加 <steering>…</steering> 用户消息，yield turn.steered
       ├─ 组装 ModelRequest（developer + 上下文片段 + 摘要 + 历史）
       ├─ BEFORE_MODEL hook
       ├─ provider.stream(request)：
       │     STARTED      → yield model.started
       │     TEXT_DELTA   → yield model.text.delta
       │     TOOL_CALL_DELTA → yield model.tool_call.delta
       │     COMPLETED    → 保存 response，yield model.completed，break
       │   异常 → yield model.failed，raise（见 §11）
       ├─ 若无 COMPLETED → RuntimeError
       ├─ AFTER_MODEL hook
       │
       ├─ 若 response.tool_calls 且 tool_executor：
       │     ├─ 追加 Message(ASSISTANT, …, tool_calls)
       │     ├─ turn.status = WAITING_TOOL
       │     ├─ 判断是否并行（registry 全部 supports_parallel）
       │     ├─ 对每个 call → yield tool.started
       │     ├─ 执行（并行 gather 或串行）→ 每个结果：
       │     │    追加 Message(TOOL, …) → _persist → yield tool.completed / tool.failed
       │     ├─ turn.status = RUNNING
       │     └─ continue   # 进入下一模型步
       │
       └─ 否则（无工具调用）：
             ├─ turn.complete(response) → COMPLETED
             ├─ 若 text 或 tool_calls → 追加 Message(ASSISTANT, …)
             ├─ _persist() → TURN_END hook → yield turn.completed → break

  finally: self._active_turn_id = None
```

若循环耗尽仍未完成（`turn.status in {RUNNING, WAITING_TOOL}`），抛 `ToolError("tool loop exceeded maximum of N model steps")`，进入失败路径。

### 3.3 终止路径的分流

`_astream_unobserved` 用 `try/except` 把三种异常/关闭分流到不同的终止状态：

```python
except GeneratorExit:
    turn.status = TurnStatus.INTERRUPTED      # 流消费者提前关闭
    turn.error = "event stream consumer closed"
    ...
    raise
except asyncio.CancelledError:
    if turn.turn_id in self._interrupt_turn_ids:
        turn.status = TurnStatus.INTERRUPTED  # 显式 interrupt
        self._interrupt_turn_ids.discard(turn.turn_id)
    else:
        turn.cancel()                          # 显式 cancel
    ...
    raise
except Exception as exc:
    turn.fail(exc)                             # 失败：FAILED + turn.failed 事件
    ...
    raise
```

关键点：**取消（cancel）与中断（interrupt）是两个不同的终止状态**，区分依据是 `_interrupt_turn_ids` 集合中是否登记了该 turn_id。

## 4. 关键接口 / 类（Key interfaces / classes）

### 4.1 Thread（`super_harness/runtime/thread.py`）

```python
@dataclass(slots=True)
class Thread:
    provider: ModelProvider
    instructions: str | None = None
    tool_registry: ToolRegistry | None = None
    tool_executor: ToolExecutor | None = None
    max_model_steps: int = 8
    context: ContextAssembler = field(default_factory=ContextAssembler)
    store: SQLiteThreadStore | None = None
    archived: bool = False
    parent_thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    summaries: list[ContextSummary] = field(default_factory=list)
    compaction_threshold_chars: int = 100_000
    compaction_retain_messages: int = 8
    hooks: HookRegistry | None = None
    observer: EventObserver | None = None
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    created_at / updated_at: datetime
    messages: list[Message]
    turns: list[Turn]
```

关键方法与签名：

```python
async def astream(input, *, tools=(), output_schema=None) -> AsyncIterator[Event]
async def _astream_unobserved(input, *, tools=(), output_schema=None) -> AsyncGenerator[Event, None]
def start(input, *, tools=(), output_schema=None) -> TurnHandle
async def arun(input, *, tools=(), output_schema=None) -> ModelResponse
def stream(input, *, tools=(), output_schema=None) -> Iterator[Event]
def run(input, *, tools=(), output_schema=None) -> ModelResponse
def compact(summary=None, *, retain_messages=None) -> tuple[Event, Event]
async def acompact(summary=None, *, retain_messages=None) -> tuple[Event, Event]
async def aclose() -> None
def debug_context() -> ContextDebugSnapshot
def archive() -> None
def fork(*, thread_id=None) -> Thread
def queue_steering(turn_id, instruction) -> None
def request_interrupt(turn_id) -> None
@property
def active_turn_id(self) -> str | None
```

同步 API 的守卫 `_sync`：若当前已在运行事件循环则抛 `RuntimeError("sync API cannot run inside an active event loop; use the async API")`，否则用 `asyncio.run` 收集。这保证了“公共同步包装不嵌套事件循环”的不变量。

### 4.2 TurnHandle（`super_harness/runtime/handle.py`）

```python
class TurnHandle:
    def __init__(self, thread, input, *, tools=(), output_schema=None) -> None
    async def events(self) -> AsyncIterator[Event]
    async def wait(self) -> ModelResponse
    async def steer(self, instruction: str) -> None
    def cancel(self) -> None
    async def interrupt(self) -> None
```

内部结构：`self._ready = asyncio.Event()`、`self._queue: asyncio.Queue[Event | object]`、`self._error`、`self._task = asyncio.create_task(self._pump(...))`。`_pump` 消费 `thread.astream` 并把每个事件放入队列；捕获到异常存入 `_error`；结束时放入哨兵 `_DONE` 并 `_ready.set()`。

- `events()` 从队列逐个产出事件，遇到 `_DONE` 结束；若 `_error` 存在则 re-raise。
- `wait()` 等待 `_task`，返回该 turn 的 `response`；若响应缺失则抛 `RuntimeError(f"turn ended with status {turn.status.value}")`。
- `steer(instruction)`：等待 `_ready`（拿到 turn_id）后调用 `thread.queue_steering`。
- `cancel()`：直接 `self._task.cancel()`（不登记中断 → 终态 `CANCELLED`）。
- `interrupt()`：先 `thread.request_interrupt(turn_id)` 再 `self._task.cancel()`（登记中断 → 终态 `INTERRUPTED`）。

### 4.3 Agent（`super_harness/agent.py`）—— Thread 的工厂

```python
class Agent:
    def __init__(self, provider, *, instructions=None, tools=(), approval=None,
                 hooks=None, observer=None, max_model_steps=8, context=(),
                 cwd=None, agents_loader=None, store=None,
                 compaction_threshold_chars=100_000, persona=None)
    def thread(self) -> Thread
    def resume(self, thread_id) -> Thread
    def fork(self, thread_id) -> Thread
    async def arun(...) -> ModelResponse
    def run(...) -> ModelResponse
    def astream(...) -> AsyncIterator[Event]
    def stream(...) -> Iterator[Event]
    async def aclose(self) -> None
```

`Agent.thread()` 用当前 provider/tool/hook 配置构造一个独立的 `Thread`；若配了 `store`，立即 `save` 快照。`Agent.resume(thread_id)` 从存储加载快照，并把快照里所有 `pending/running/waiting_tool` 的 Turn 标记为 `INTERRUPTED`（`error = "interrupted before resume"`），绝不把进行中的 Turn 静默恢复成完成态。

### 4.4 上下文装配（`super_harness/context/fragments.py`）

```python
class ContextAssembler:
    max_chars: int = 100_000
    fragments: list[ContextFragment]
    def add(self, fragment) -> None
    def extend(self, fragments) -> None
    def ordered(self) -> tuple[ContextFragment, ...]   # 去重 → 按权威排序 → 预算截断
    def messages(self) -> tuple[Message, ...]          # 渲染为 <context> 用户消息

def redact_text(value: str) -> str
```

### 4.5 AGENTS.md 解析器（`super_harness/context/agents_md.py`）

```python
@dataclass(frozen=True, slots=True)
class AgentsMdLoader:
    root_markers: tuple[str, ...] = (".git",)
    max_bytes: int = 32_768
    filenames: tuple[str, ...] = ("AGENTS.override.md", "AGENTS.md")
    def project_root(self, cwd: Path) -> Path
    def discover(self, cwd) -> tuple[Path, ...]
    def load(self, cwd) -> tuple[ContextFragment, ...]  # ContextKind.PROJECT, role USER
```

## 5. 并发 / 取消（Concurrency / cancellation）

### 5.1 单活动 Turn 约束

`Thread._active_turn_id` 是单活动守卫：`_astream_unobserved` 在开头检查，若已有活动 Turn 则抛 `RuntimeError("thread already has an active turn")`。因此**同一时刻一个 Thread 只能有一个活动 Turn**，历史通过 `turns` 列表按顺序追加。

### 5.2 流式是权威路径，取消向下传播

流式路径是权威路径。`arun`/`run` 只是 `astream`/`stream` 的薄消费者：它们循环收集事件，只在遇到 `turn.completed` 时取回 `response`，否则抛 `RuntimeError("turn ended without a response")`。

取消通过异步生成器传播到 provider（进而传播到 HTTPX）：`_astream_unobserved` 中 `async for model_event in self.provider.stream(request)` 外层捕获 `asyncio.CancelledError` 后 `raise`（见 §3.3），`finally` 保证 `_active_turn_id` 被清空。provider 层负责关闭活动 HTTP 流（见 `docs/research/codex/model-provider-and-streaming.md`：dropping/cancelling a stream cancels downstream work）。

### 5.3 转向（steering）在安全检查点注入

`queue_steering(turn_id, instruction)` 把指令追加到 `_steering_by_turn[turn_id]`，**不立即注入**。真正的注入发生在下一模型步的检查点：每步开始时 `for instruction in self._steering_by_turn.pop(turn.turn_id, [])`，把指令包装成 `<steering>{instruction}</steering>` 的用户消息追加进历史，并 `yield turn.steered`。这样转向不会打断正在进行的模型调用，只在模型步边界安全地生效。

### 5.4 并行工具执行

当一次响应含多个工具调用且注册表中所有工具都 `supports_parallel` 时，用 `asyncio.gather` 并发执行：

```python
if parallel:
    results = await asyncio.gather(
        *(self.tool_executor.execute(call) for call in response.tool_calls)
    )
else:
    results = []
    for call in response.tool_calls:
        results.append(await self.tool_executor.execute(call))
```

工具结果按调用顺序 zip 回写为 `Message(TOOL, …)`，保证顺序稳定。取消会传播到并行任务（gather 的任一子任务被取消，其余也会被取消）。

### 5.5 多活动 Turn 的控制（TurnHandle）

`start()` 返回 `TurnHandle`，其 `_pump` 是一个 `asyncio.create_task`，在后台泵送同一条权威 Thread 事件流。因此：

- 调用方可在不阻塞流消费的前提下，通过 `steer` / `interrupt` / `cancel` 控制活动 Turn。
- `_ready` 事件在首个带 `turn_id` 的事件到达时置位，保证 `steer`/`interrupt` 在拿到 turn_id 前不会误报“turn is no longer active”。
- `_task.done()` 检查防止对已结束的 Turn 注入转向。

## 6. 持久化（Persistence）

`SQLiteThreadStore`（`super_harness/persistence/sqlite.py`）用带版本控制的 SQLite 表（`SCHEMA_VERSION = 1`）做事务性全量快照：

- `threads` 表：`thread_id`（主键）、`created_at`、`updated_at`、`instructions`、`archived`、`parent_thread_id`、`metadata_json`、`summaries_json`。
- `messages` 表：`(thread_id, position)` 主键，`data_json`。
- `turns` 表：`(thread_id, position)` 主键，`data_json`。

要点：

- **事务性**：`save` 在 `with self._lock, self._connection:` 内先 upsert `threads`，再 `DELETE` 旧的 messages/turns，再批量插入——任何一步失败整批回滚，绝不产生半写状态。
- **provider 中性**：序列化的是中性消息、工具调用、用量、结构化输出、摘要 ID、时间戳、归档状态、fork 谱系，不含 Responses API item、rollout JSONL、OpenAI ID 或账户元数据。
- **WAL 模式 + foreign_keys**，`check_same_thread=False` 配合 `threading.RLock` 保证跨线程安全。
- `load` 返回 `ThreadSnapshot`（`thread_id/created_at/updated_at/instructions/archived/parent_thread_id/metadata/messages/turns/summaries`）。
- `archive(thread_id, archived=True)` 是元数据操作，不删除历史；`ids()` 列出未归档 Thread。

Thread 的 `_persist()` 在关键节点调用：turn 启动后、每个工具结果回填后、turn 完成后、终止状态落定后、压缩后。`fork()` 以显式快照边界派生新 ID（`parent_thread_id = self.thread_id`）并持久化。

恢复语义（`Agent.resume`）：恢复原始 ID 与历史；**进行中的 Turn（pending/running/waiting_tool）标记为 `INTERRUPTED`，而不是静默完成**——因为无法从快照重建未完成的模型调用。

## 7. 事件 / 可观测性（Events / observability）

### 7.1 Thread 发出的事件类型（稳定点号命名）

| 事件类型 | 关联 | 载荷关键字段 |
|---|---|---|
| `turn.started` | turn | — |
| `turn.steered` | turn | `instruction` |
| `turn.completed` | turn | `response` |
| `turn.failed` | turn | `error_type`, `message` |
| `model.started` | turn | `provider`, `model`, `step` |
| `model.text.delta` | turn | `delta`, `step` |
| `model.tool_call.delta` | turn, tool_call | `index`, `name`, `delta`, `step` |
| `model.completed` | turn | `response`, `usage`, `tool_calls`, `provider`, `model`, `step` |
| `model.failed` | turn | `provider`, `model`, `step`, `error_class`, `message` |
| `tool.started` | turn, tool_call | `name`, `arguments` |
| `tool.completed` | turn, tool_call | `result`, `success` |
| `tool.failed` | turn, tool_call | `result`, `success` |
| `compaction.started` | thread | `before_messages`, `summarized_messages` |
| `compaction.completed` | thread | `after_messages`, `summary_id` |

每个事件都携带 `event_id`（uuid4）与 UTC `timestamp`，并视情况填充 `thread_id` / `turn_id` / `tool_call_id`，从而在 trace 父级形成 thread→turn→model/tool 的关联链。载荷一律只读。

### 7.2 观察者

`Thread.astream` 在每个事件上调用 `observer.observe(event)`（若配置了 observer），并且兼容同步与异步返回值：

```python
async for event in operation:
    if self.observer is not None:
        outcome = self.observer.observe(event)
        if inspect.isawaitable(outcome):
            await cast(Awaitable[object], outcome)
    yield event
```

观察路径位于不可变生命周期事件的下游，从不控制调度或 provider 响应（详见 `docs/research/codex/observability-and-hardening.md`）。

### 7.3 上下文调试快照

`Thread.debug_context()` 返回 `ContextDebugSnapshot(thread_id, entries, history_messages, estimated_characters)`。每个 `ContextDebugEntry` 含 `kind/source/role/priority/content`，其中 `content` 已经过 `redact_text` 脱敏（遮蔽 `api_key`/`token`/`secret`/`password` 赋值与 `sk-…` 形态 token）。这使“调试上下文”成为一等公共值，而非仅存在于 app-server 的诊断面。

### 7.4 Hook 事件

运行时在多个生命周期点分发 Hook（`HookEvent`）：`SESSION_START`/`SESSION_END`、`TURN_START`/`TURN_END`、`USER_PROMPT`、`BEFORE_MODEL`/`AFTER_MODEL`、`PRE_COMPACT`/`POST_COMPACT`、`ERROR`。Hook 可以改写输入（如 `USER_PROMPT` 改写 `input`、`BEFORE_MODEL` 改写 `request`、`PRE_COMPACT` 改写 `summary`/`retain_messages`），也可以 `deny` 拒绝（`HookError` 抛出）。失败的 Hook 接收原始异常。

## 8. Codex 参考（Codex reference）

本项目锁定并审视了 Codex（Rust）的对应实现，证据记录在：

- `docs/research/codex/agent-runtime-thread-turn.md` —— Thread/Turn 生命周期、事件、取消/中断行为契约与不变量。
- `docs/research/codex/durable-thread-context-compaction.md` —— 持久化、上下文片段、AGENTS.md 解析、压缩的契约与不变量。
- `docs/research/codex/model-provider-and-streaming.md` —— 流式权威路径、提前关闭可重试、取消传播到 HTTPX。

镜像源码在 `references/codex/`，被检视的关键文件包括：

- `codex-rs/core/src/session/turn.rs`、`codex-rs/core/src/codex_thread.rs`、`codex-rs/core/src/thread_manager.rs`
- `codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs`、`.../v2/turn.rs`
- `codex-rs/thread-store/src/lib.rs`、`.../in_memory.rs`、`.../live_thread.rs`、`.../types.rs`
- `codex-rs/context-fragments/src/fragment.rs`、`.../additional_context.rs`
- `codex-rs/core/src/agents_md.rs`、`codex-rs/core/src/context_manager/history.rs`、`.../normalize.rs`、`codex-rs/core/src/compact.rs`

从 Codex 提炼出的行为契约（本项目逐条复现）：

- Thread 拥有有序历史与 Turn；Turn 拥有一次用户发起执行的显式生命周期状态、时间戳与错误记录。
- 运行时追加用户输入、调用模型、记录助手输出，仅在规范化调用需要下一编排步时继续。
- 事件携带关联标识并暴露生命周期，客户端无需检查内部状态。
- 取消与中断是可观测的终止结果；失败/取消的 Turn 保留诊断状态。
- 上下文片段保留角色、分类、来源与 marker 身份，而非退化为不可追踪的字符串拼接。
- AGENTS 指令从项目根到 cwd 发现、绝不越过根、本地 override 优先、有总字节预算。
- 压缩保留“摘要 + 最近后缀”并记录显式边界/事件。

## 9. Python 原生重设计（Python-native redesign）

从 Codex 的 Rust 实现到 Python 的映射：

| Rust（Codex） | Python（Super Harness） |
|---|---|
| `turn.rs` 状态机 | `TurnStatus`（StrEnum）+ `Turn` dataclass 方法守卫 |
| `codex_thread.rs` | `Thread` dataclass + `_astream_unobserved` 生成器 |
| `thread_manager.rs` | `Agent`（Thread 工厂）+ `SQLiteThreadStore` |
| app-server 协议 v2 thread/turn | 不可变 `Event`（通用事件信封） |
| `context-fragments` | `ContextFragment` + `ContextAssembler`（权威排序/去重/预算/来源） |
| `agents_md.rs` | `AgentsMdLoader`（`.git` 根发现 + override 优先 + 字节上限） |
| `compact.rs` | `compact`/`acompact` + `extractive_summary` + `ContextSummary` |
| client 流式 | `ModelProvider.stream` → `AsyncIterator[ModelStreamEvent]` |

Python 原生设计决策：

- 流式 API（`astream`）是权威路径，`arun`/`run` 是薄消费者。
- 事件用稳定点号名 + 通用不可变信封（`Event`），与 Phase 0 一致。
- 默认压缩器是**确定性、抽取式**的（`extractive_summary`），不发起额外 provider 调用；应用可显式提供更高质量的摘要。
- 调试快照（`debug_context`）从阶段 3 起就是一等公共值。

## 10. 有意差异（Intentional differences）

- **存储形态**：Codex 采用配对 JSONL + SQLite 元数据；本项目 V1 用 SQLite 作为唯一权威存储，事务性全量快照。
- **默认压缩器**：Codex 的压缩可能依赖模型；本项目默认用确定性的抽取式摘要（保留安全/权限关键词行），高质量摘要由应用显式注入，避免强制额外模型调用。
- **单活动 Turn 约束**：本项目当前在内存运行中强制“一个 Thread 同一时刻只有一个活动 Turn”，用 `_active_turn_id` 守卫；这与 Codex 通过 turn-scoped session 复用一个 provider 会话的模型接近，但更严格地约束了并发入口。
- **`WAITING_TOOL` 显式中间态**：工具等待被建模为独立的非终止状态，区别于 `RUNNING`，使工具阶段的可观测性与恢复语义更清晰。
- **取消与中断分离**：`cancel()` 与 `interrupt()` 产生两个不同的终止状态，而不是把两者合并成一个“停止”。

## 11. 失败模型（Failure model）

### 11.1 异常类型与映射

| 条件 | 异常 | Turn 终态 |
|---|---|---|
| 运行已归档 Thread | `RuntimeError("cannot run an archived thread")` | —（不建 Turn） |
| Thread 已有活动 Turn | `RuntimeError("thread already has an active turn")` | — |
| 空输入 | `ValueError("turn input must be non-empty")` | — |
| 用户提示被 Hook 拒绝 | `HookError` | 失败路径 |
| 工具循环超预算 | `ToolError("tool loop exceeded maximum of N model steps")` | FAILED |
| provider 流无 COMPLETED | `RuntimeError("provider completed without a normalized response")` / `"...ended without a completed event"` | FAILED |
| provider 抛出 | 原始异常（先发 `model.failed`） | FAILED |
| `cancel()` | `asyncio.CancelledError` | CANCELLED |
| `interrupt()` | `asyncio.CancelledError` + 登记 | INTERRUPTED |
| 流消费者提前关闭 | `GeneratorExit` | INTERRUPTED |
| 恢复前的挂起 Turn | —（`resume` 直接标记） | INTERRUPTED |
| 同步 API 在事件循环内调用 | `RuntimeError("sync API cannot run inside an active event loop")` | — |

任何异常路径都会先 `_persist()`（终止状态落盘），再（若配置）分发 `ERROR` hook，最后 `yield turn.failed` 并 re-raise。这样失败对下游既是事件又是异常，二者都保留诊断。

### 11.2 流提前关闭（可重试协议失败）

provider 流只有在 `COMPLETED` 之后才算成功；提前关闭属于“在配置的流预算内可重试的协议失败”（由 provider 层执行重试，见 `model-provider-and-streaming.md`）。Thread 侧对“流结束却没有 completed”一律视为错误，不静默接受部分结果。

### 11.3 重试 / 超时归属

- 模型重试与流超时由 provider 层负责（有界重试预算、认证/无效请求不重试）。
- Thread 侧不重试：一次失败即进入 FAILED 终态并 re-raise。
- 工具执行有自身的限时/审批路径（`ToolExecutor`），其拒绝与校验失败以失败的 `ToolResult` **数据**返回以便模型恢复；而任务取消仍作为异常传播。

## 12. 扩展点（Extension points）

- **Provider**：实现 `ModelProvider` 协议（`stream`/`complete`/`aclose` + `name`/`capabilities`），即可插入任意模型后端，运行时与 provider SDK 零耦合。
- **观察者**：实现 `EventObserver.observe`，接入任意可观测性后端；事件流是只读的下游视图。
- **Hooks**：`HookRegistry` 注册 `(priority, source, name)` 处理器，可在 `USER_PROMPT`/`BEFORE_MODEL`/`PRE_COMPACT` 等点改写输入/请求/压缩参数，或 `deny` 拒绝。
- **上下文片段**：通过 `Agent(context=[...])` 注入任意 `ContextKind` 的 `ContextFragment`（如 MEMORY、RAG、PERSONA、SKILL），参与权威排序与预算。
- **AGENTS 加载**：传入自定义 `AgentsMdLoader` 可替换根标记、文件名与字节上限。
- **压缩摘要**：`acompact(summary=...)` 或 `PRE_COMPACT` hook 可注入应用级摘要，替代默认抽取式摘要。
- **持久化**：`store` 参数接受任意实现 `save`/`load`/`archive`/`ids` 的存储；V1 为 `SQLiteThreadStore`。

## 13. 测试（Tests）

对应测试文件（`tests/`）：

- `tests/test_agent_runtime.py` —— 基本 async/sync 运行追加 user/assistant 历史；重复运行复用历史但产生独立有序 Turn；流式按序发出 turn/model 生命周期与文本增量；provider 失败标记 FAILED 并发出单个 `turn.failed` 终态事件；取消标记 CANCELLED 且保留历史；同步方法在已运行事件循环中拒绝。
- `tests/test_context_and_persistence.py` —— 上下文权威排序、去重、预算、来源、脱敏；AGENTS.md 根/嵌套顺序、override 优先、字节上限、不越过根；创建/保存/重开/resume 稳定 ID、fork 隔离与谱系、archive 阻止新运行但不删历史；事务回滚与 schema 版本。
- `tests/test_events.py`、`tests/test_model_types.py` —— 事件信封校验与模型值不可变/校验。
- `tests/test_examples.py` —— 运行 `examples/` 中 91 个示例的回归（覆盖 `02_streaming`、`07_durable_thread`、`08_agents_context_debug`、`09_compaction_and_control` 等）。
- `tests/test_hooks.py`、`tests/test_tools.py` —— Hook 分发与工具执行/审批/取消传播。

示例验证链（可运行，见 §“链接”）：
- `examples/02_streaming/main.py` —— 消费相关运行时事件（`model.text.delta`）。
- `examples/07_durable_thread/main.py` —— 持久化/重开/resume/fork。
- `examples/08_agents_context_debug/main.py` —— 分层 AGENTS.md 发现 + 脱敏上下文。
- `examples/09_compaction_and_control/main.py` —— 压缩 + 中断活动 TurnHandle。
- `examples/84_compaction_custom_summary.py`、`examples/85_compaction_retention.py` —— 自定义摘要 / 保留后缀。
- `examples/47_agent_budget_cancel.py` —— 多 Agent 预算与中断（跨章参考）。

## 14. 限制 / 未来工作（Limitations / future work）

- **单活动 Turn**：当前一个 Thread 同一时刻只允许一个活动 Turn；多 Turn 并发需要引入显式的并发策略与独立会话隔离。
- **压缩质量**：默认抽取式摘要可能丢失细节；更好的做法是允许 provider 生成摘要（当前已支持通过 `acompact(summary=...)` 显式注入，但尚无内置“模型压缩”调用路径）。
- **内存运行**：Phase 1/2 的 `Thread` 在内存中运行；恢复/持久化完整路径依赖 `SQLiteThreadStore`，跨进程状态恢复随持久化扩展继续演进。
- **流中断重试**：流提前关闭的重试完全交给 provider；Thread 侧没有跨模型步的自动续跑，一次失败即终态。
- **上下文预算粒度**：预算按总字符数截断到片段边界；尚无按 token 预算或按权威加权预算。
- **AGENTS 缓存**：每次构造 Agent 都重新解析 AGENTS 文件；尚无缓存/失效策略。
- **steering 检查点粒度**：转向只能在模型步边界注入；未来可支持在工具调用间或更细粒度检查点注入。
- **归档语义**：`archive` 阻止新运行但保留历史；尚无生命周期化的删除/保留策略。

## 链接

- 可运行示例：`examples/02_streaming`、`examples/07_durable_thread`、`examples/08_agents_context_debug`、`examples/09_compaction_and_control`、`examples/84_compaction_custom_summary`、`examples/85_compaction_retention`
- [查看完整可运行示例 02_streaming](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)
- [查看完整可运行示例 07_durable_thread](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py)
- [查看完整可运行示例 08_agents_context_debug](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)
- [查看完整可运行示例 09_compaction_and_control](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)
- [查看完整可运行示例 84_compaction_custom_summary](https://github.com/Sitozzmonash/superharness/blob/main/examples/84_compaction_custom_summary.py)
- [查看完整可运行示例 85_compaction_retention](https://github.com/Sitozzmonash/superharness/blob/main/examples/85_compaction_retention.py)
- 研究文档：`docs/research/codex/agent-runtime-thread-turn.md`、`docs/research/codex/durable-thread-context-compaction.md`、`docs/research/codex/model-provider-and-streaming.md`
- API 参考：`website/docs/api-reference.md`
