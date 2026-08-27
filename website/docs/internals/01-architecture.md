---
id: internals-architecture
title: 设计目标与高层架构
sidebar_position: 1
description: Super Harness 的设计目标、非目标、Codex 参考策略、异步优先分层架构、运行时循环与并发架构。
---

# 设计目标与高层架构

本章是 Internals 系列的第一章，回答两个问题：**Super Harness 为什么被设计成现在这样**（设计目标与非目标），以及**它整体上是如何组织起来的**（异步优先的分层架构、运行时循环、并发架构）。后续各章会深入每一个子系统（模型与流式、Tool 流水线、持久化、上下文与压缩、RAG、记忆、Skills/MCP、插件/钩子、自主编排、确定性工作流、可观测性、CLI），本章为它们提供共同的骨架。

本章所有描述都对应 `src/super_harness/` 下的真实实现。引用 API 时给出真实签名；行为描述与 `src/super_harness/agent.py`、`src/super_harness/models/`、`src/super_harness/runtime/` 中的代码一致。

## 设计目标（Design goals）

Super Harness 是一个**自研的 Python 异步优先 agent 运行时**。它并非对任何现有产品的封装，而是以 OpenAI Codex 的运行时为**研究参考**、以 Python 原生方式重新实现的一套分层架构。核心设计目标如下。

### 目标一：Python 原生（Python-native）

- 整个运行时使用 Python 3.11+ 的 `asyncio` 构建，异步为第一公民。
- 公开 API 同时提供异步（`arun` / `astream`）与同步（`run` / `stream`）两种入口，但**同步入口只是异步实现的薄消费者**，绝不复制一套同步逻辑。
- 通过 `dataclass(frozen=True, slots=True)` 定义不可变值，杜绝跨层共享可变状态的隐患。
- 依赖极简：模型层只依赖 `httpx`；不依赖任何 OpenAI/供应商 SDK 的响应类。

### 目标二：受 Codex 启发而非封装 Codex（Codex-inspired, not wrapped）

- Super Harness **不调用、不导入、不依赖** OpenAI Codex 的可执行文件或 Rust crate。
- 而是在实现每个功能前，先阅读一个**固定版本**的 Codex 源码，提取其行为契约与不变量，再在 Python 中重新实现。
- 固定的 Codex 提交记录在 `references/CODEX_PIN.md`，源码以浅 Git 子模块形式保留在 `references/codex/`。
- 每个功能的 Codex 研究笔记存放在 `docs/research/codex/`，并逐条列出"移除了哪些 OpenAI 耦合"。

### 目标三：OpenAI 可选（OpenAI optional）

- 运行时不依赖 OpenAI 的账号体系、ChatGPT 头、prompt-cache 标识或 OpenAI SDK。
- `OpenAICompatibleProvider` 只是把中性值映射成 Chat Completions 或 Responses 两种**线协议**的适配器；这两种协议都可通过配置选用，且都可替换为任何兼容实现。
- provider 返回的响应对象永远不越过 provider 边界——运行时只见中性不可变值。

### 目标四：中国可用（China-ready）

- Chat Completions 被作为一等线协议支持，因为它在中国可用的 OpenAI 兼容服务中广泛存在。
- 内置 `DeepSeekProvider`，提供官方 base URL（`https://api.deepseek.com`）、环境变量（`DEEPSEEK_API_KEY`）与能力声明。
- DeepSeek 原生 API 拒绝 OpenAI 的 `developer` 角色，适配器在序列化时把 `developer` 映射为 `system`；DeepSeek 还拒绝 `response_format: json_schema`，适配器放宽为 `json_object` 并本地校验 schema 一致性。
- RAG、Web Search、Vision 通过独立协议接入（如智谱 `ZhipuWebSearchProvider` / `ZhipuVisionProvider`），见后续"外部知识流水线"章节。

### 目标五：RAG 作为外部契约（RAG external contract）

- RAG 不是运行时内置的实现细节，而是 `KnowledgeRouter` 与三个异步协议（`WebSearchProvider`、`RAGProvider`、`VisionProvider`）之间的外部契约。
- 具体适配器拥有 provider 特有的 HTTP 形态，返回不可变的中性值（`RAGDocument`、`SearchResponse`、`VisionResult`）。
- 搜索结果与 RAG 上下文被标记为 `ContextKind.RAG`，以用户权威渲染。

## 非目标（Non-goals）

明确声明**不**做什么，防止设计被"什么都做"拖垮：

- **不做 Python 对 Codex 的逐行移植**。Codex 是 Rust 实现；Super Harness 只借鉴其行为契约与不变量，不保留其内部结构。
- **不内置模型托管**。不捆绑、不下载任何模型权重；模型一律通过 provider 远程访问。
- **不内置向量数据库**。RAG 的检索端由外部服务提供，运行时只约定协议。
- **不追求多进程隔离作为默认**。本地 Sandbox 在取消时终止进程组，但无法约束任意子进程系统调用；完整隔离交给 Docker 后端。
- **不静默回退 provider**。`FallbackProvider` 只做显式、可观测的切换，且**一旦已产生可见输出就不再回退**（避免半截内容拼接）。
- **不隐藏失败**。流未走到终态即视为失败并进入有界重试预算，而非"尽力而为"地吞掉。

## 分阶段演进（Phased evolution）

架构并非一次性成型，而是按阶段交付（旧版 `website/docs/internals.md` 保留了这个叙述）：

- **阶段 1**：分离出三个核心层次（models → provider 线映射 → Agent/Thread/Turn 编排），确立流路径为权威路径。
- **阶段 2**：增加确定性的 `ToolRegistry` 与 `ToolExecutor` 流水线（解析 → 校验 → 审批 → 限时调用 → 规范化 → 截断）。
- **阶段 3**：增加事务性 SQLite 快照持久化、上下文组装与压缩。
- 之后的功能（RAG、记忆、Skills/MCP、插件/钩子、自主编排、确定性工作流、可观测性、CLI）按各自研究笔记独立演进。

## 高层架构总览（High-level architecture）

核心是**异步优先、三层分离**。运行时只依赖精简的 `ModelProvider` 协议，绝不依赖任何 provider SDK 的响应类。

```
┌────────────────────────────────────────────────────────────────────┐
│  第 3 层：编排（orchestration）                                      │
│  Agent ──创建──▶ Thread ──产生──▶ Turn / TurnHandle                │
│  有序历史 · 生命周期状态 · 相互关联的公共事件（Event）                │
└───────────────┬────────────────────────────────────────────────────┘
                │ 仅依赖中性不可变值（ModelRequest / ModelStreamEvent）
┌───────────────▼────────────────────────────────────────────────────┐
│  第 2 层：线映射（wire mapping）                                     │
│  OpenAICompatibleProvider ──Chat Completions / Responses──▶ HTTP   │
│  DeepSeekProvider（子类）· FallbackProvider（装饰器）                │
│  把中性值编码为 HTTP 负载，并把回复解码回中性值                        │
└───────────────┬────────────────────────────────────────────────────┘
                │ 基于 httpx.AsyncClient
┌───────────────▼────────────────────────────────────────────────────┐
│  第 1 层：中性值（neutral values）                                   │
│  super_harness.models.types                                        │
│  Message · ToolDefinition · ToolCall · Usage · ModelRequest         │
│  ModelResponse · ModelStreamEvent · ModelCapabilities               │
│  全部不可变（frozen dataclass / MappingProxyType）                   │
└────────────────────────────────────────────────────────────────────┘
```

三层之间唯一的通行证是第 1 层的不可变值。第 2 层把中性值编码成 HTTP 负载、把 provider 回复解码回中性值；第 3 层只消费中性值并产出公共 `Event`。

### 职责划分（Responsibilities）

- **第 1 层（`models/types.py`）**：定义消息、工具 schema、工具调用、用量、能力、请求、响应、流事件等不可变值；负责 JSON 有效性校验（深度、循环、非有限数、条目上限、工具名合法字符）。
- **第 2 层（`models/openai_compatible.py` 等）**：`ModelProvider` 协议的全部实现方。负责认证、HTTP 传输、重试/退避、SSE 解析、流终态判定、结构化输出解析。
- **第 3 层（`agent.py` + `runtime/`）**：`Agent` 持有配置与 provider，`Thread` 持有有序历史与 Turn，`Turn` 持有一次执行的状态机。负责编排、上下文组装、工具循环、持久化、事件发射。

## 数据模型（Data model）

核心不可变值（全部在 `super_harness/models/types.py`，`frozen=True, slots=True`）：

```python
class MessageRole(StrEnum):
    SYSTEM = "system"
    DEVELOPER = "developer"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: JsonObject   # MappingProxyType 冻结，构造时校验

@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: JsonObject
    raw_arguments: str

@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    streaming: bool = True
    tools: bool = True
    structured_output: bool = True
    reasoning: bool = False
    parallel_tool_calls: bool = True
    wire_apis: tuple[str, ...] = ("chat_completions",)

@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: Sequence[Message]
    tools: Sequence[ToolDefinition] = ()
    output_schema: JsonObject | None = None
    temperature: float | None = None
    parallel_tool_calls: bool = True
    extra: JsonObject = ...   # 构造时冻结为 MappingProxyType

@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = ...
    response_id: str | None = None
    finish_reason: str | None = None
    output_json: JsonObject | None = None

class ModelStreamEventType(StrEnum):
    STARTED = "started"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    COMPLETED = "completed"

@dataclass(frozen=True, slots=True)
class ModelStreamEvent:
    type: ModelStreamEventType
    delta: str = ""
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    response: ModelResponse | None = None
```

要点：

- **防御性冻结**。`ModelRequest`、`ToolDefinition`、`ToolCall`、`ModelResponse` 构造时通过 `MappingProxyType` 冻结所有 JSON 映射，并递归校验 JSON 合法性（深度 ≤ 32、无环、无非有限数、对象/数组 ≤ 10000 项、键必须是字符串）。`test_model_types.py` 验证了这一点。
- **工具名约束**。工具名必须匹配 `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`；工具调用 ID 必须为 1–256 个无控制字符的字符；原始参数不超过 100 万字符。
- **中性消息存储**。assistant 的工具调用与工具输出以中性 `Message` 存储；Chat Completions 接收 `tool_calls` + `tool` 消息，Responses 接收 `function_call` + `function_call_output` 项（由第 2 层负责双向转换）。

### 运行时状态对象

```python
class TurnStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_TOOL = "waiting_tool"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"

@dataclass(slots=True)
class Turn:
    input: str
    turn_id: str = ...
    status: TurnStatus = TurnStatus.PENDING
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    response: ModelResponse | None = None
    error: str | None = None
    # start() / complete(response) / fail(error) / cancel()
```

`Turn` 的状态机只有合法转移：`PENDING → RUNNING → COMPLETED`，或在任意点转向 `FAILED` / `INTERRUPTED` / `CANCELLED`。`complete()` 只接受 `RUNNING` 或 `WAITING_TOOL`；`start()` 只接受 `PENDING`。每个 Turn **恰好进入一个终态**。

## 运行时循环（Runtime loop）

运行时循环在 `Thread._astream_unobserved`（`runtime/thread.py`）中实现，是整个系统的核心。要点：

1. **模型步预算（model-step budget）**。`max_model_steps`（默认 8）是有界的模型步数预算，防止工具无限循环。`Agent` 构造时若 `< 1` 抛 `ValueError`。每一步调用一次模型；工具循环结束后若仍处于 `RUNNING`/`WAITING_TOOL`，抛 `ToolError("tool loop exceeded maximum of ... model steps")`。
2. **流路径是权威路径（stream path authoritative）**。运行时总是通过 `provider.stream(request)` 驱动模型；`arun`/`run` 只是把 `astream` 的事件流收集成最终 `ModelResponse` 的薄消费者。
3. **终态事件**。provider 流只有在 Chat Completions 的 `[DONE]` 或 Responses 的 `response.completed` 之后才算成功；`_stream_once` 中若流在终态事件前关闭，抛 `httpx.RemoteProtocolError("stream closed before terminal completion event")`，可在流式重试预算内重试。
4. **步骤内事件序列**：`model.started` →（`model.text.delta` / `model.tool_call.delta`）→ `model.completed`。
5. **工具循环**：若响应带 `tool_calls`，把 assistant 消息入历史、置 `WAITING_TOOL`，执行工具（并行用 `asyncio.gather`，否则顺序），把每条 `tool` 消息入历史，回到步骤 1。
6. **终态**：`turn.complete(response)`，发 `turn.completed`；`turn.failed` 用于异常；`turn.started` 在开头发出。

简化伪代码：

```python
async def _astream_unobserved(self, input, *, tools, output_schema):
    # 校验 archived / active turn / 非空输入
    # hooks: SESSION_START（首次）、USER_PROMPT
    turn = Turn(input); self._active_turn_id = turn.turn_id
    self.messages.append(Message(USER, input)); turn.start()
    yield Event("turn.started", ...)
    if 历史长度 > compaction_threshold_chars:
        async for e in self.acompact(): yield e
    for step in range(1, self.max_model_steps + 1):
        # 注入排队中的 steering 指令
        request = self._request(tools=tools, output_schema=output_schema)
        # hooks: BEFORE_MODEL
        async for model_event in self.provider.stream(request):
            # 映射为 model.started / model.text.delta / model.tool_call.delta / model.completed
            if completed: response = ...; break
        # hooks: AFTER_MODEL
        if response.tool_calls and self.tool_executor is not None:
            # 入 assistant 历史，置 WAITING_TOOL，执行工具，入 tool 历史
            continue
        turn.complete(response); 入 assistant 历史; self._persist()
        # hooks: TURN_END
        yield Event("turn.completed", ...); break
    if turn.status in {RUNNING, WAITING_TOOL}:
        raise ToolError(f"tool loop exceeded maximum of {self.max_model_steps} model steps")
```

生命周期图（一个 Turn 内，含工具循环）：

```
turn.started
   │
   ▼
┌─▶ model.started ─▶ model.text.delta / model.tool_call.delta ─▶ model.completed
│      │                                                              │
│      └────────────── BEFORE_MODEL / AFTER_MODEL hooks ──────────────┘
│      │
│      ├─ 有 tool_calls ─▶ tool.started ─▶ (并行/顺序) ─▶ tool.completed / tool.failed
│      │                     │                                        │
│      │                     └──────────── 回到下一个模型步 ◀──────────┘
│      │
│      └─ 无 tool_calls ─▶ turn.completed（终态）
│
└── 超过 max_model_steps ─▶ ToolError（turn.failed）
```

## 并发与取消（Concurrency / cancellation）

并发架构完全建立在 `asyncio` 之上：

- **事件循环约束**。同步入口（`run`/`stream`）在**没有**运行中的事件循环时用 `asyncio.run` 收集异步操作；若检测到已有活动事件循环，抛 `RuntimeError("sync API cannot run inside an active event loop; use the async API")`。`test_agent_runtime.py` 验证了这一点。
- **TurnHandle 泵送**。`TurnHandle`（`runtime/handle.py`）在构造时用 `asyncio.create_task(self._pump(...))` 把 `thread.astream` 的事件泵进一个 `asyncio.Queue`，用 `_DONE` 哨兵表示结束；`events()` 是异步消费者，`wait()` 等待任务完成并取回 `ModelResponse`。
- **工具并行执行**。一个 Turn 内多个工具调用若都声明 `supports_parallel`，则用 `asyncio.gather` 并发执行；否则顺序执行。
- **工具超时**。`ToolExecutor.execute` 用 `asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)` 限时调用；超时返回 `success=False` 的 `ToolResult`（error_type=`TimeoutError`），让模型可恢复，**而不是**抛出中断整个 Turn。
- **信号量（semaphores）**。在确定性工作流引擎（`orchestration/workflow.py`）中，独立节点成为 asyncio Task 后通过 `asyncio.Semaphore(self.max_concurrency)` 限流。
- **Conditions 而非轮询**。在自主多代理管理器（`orchestration/autonomous.py`）中，事件历史与完成信号用 `asyncio.Condition` 的 `wait()`/`notify_all()`，等待方阻塞而非轮询。
- **取消传播**。取消通过异步生成器传播到 HTTPX——`provider.stream` 是异步生成器，消费方 `break`/取消会关闭底层 HTTP 流。`OpenAICompatibleProvider._stream_once` 用 `async with self._http().stream(...)`，退出即关闭。
- **中断 vs 取消**。`TurnHandle.interrupt()` 先把 turn_id 注册进 `thread.request_interrupt()` 再取消任务；`Thread` 捕获 `CancelledError` 时，若该 turn 在 `_interrupt_turn_ids` 中则标记 `INTERRUPTED`，否则标记 `CANCELLED`。这是两个不同的终态。
- **消费方提前关闭**。事件流消费者提前退出会触发 `GeneratorExit`，Turn 被标记 `INTERRUPTED`（error="event stream consumer closed"）。

## 持久化（Persistence）

- `Agent` 可选接收 `SQLiteThreadStore`；`thread()` 创建后立即 `store.save(thread)`。
- `SQLiteThreadStore` 把 Thread 快照写入**带版本控制的 SQLite 表**，存储 Thread 元数据、有序消息、有序 Turn、摘要、用量、时间戳、归档状态与 fork 谱系，全部保持 provider 无关。
- `ThreadSnapshot`（`persistence/sqlite.py`）是不可变快照：`thread_id, created_at, updated_at, instructions, archived, parent_thread_id, metadata, messages, turns, summaries`。
- `resume(thread_id)` 从 store 加载快照重建 `Thread`；**被恢复的 `pending`/`running`/`waiting_tool` Turn 会被标记为 `INTERRUPTED`**（error="interrupted before resume"），而不是静默完成。
- `fork(thread_id)` = `resume(thread_id).fork()`，生成带 `parent_thread_id` 的新 Thread。
- 详情见后续持久化章节与 `docs/research/codex/durable-thread-context-compaction.md`。

## 事件与可观测性（Events / observability）

- 运行时发射不可变的 `Event`（`runtime/events.py`）：`type, event_id, timestamp, thread_id, turn_id, agent_id, parent_agent_id, workflow_run_id, node_id, tool_call_id, trace_id, span_id, payload`。payload 被防御性拷贝并暴露为只读映射。
- 事件类型使用稳定的点分名称：`turn.started` / `turn.completed` / `turn.failed` / `model.started` / `model.text.delta` / `model.tool_call.delta` / `model.completed` / `model.failed` / `tool.started` / `tool.completed` / `tool.failed` / `turn.steered` / `compaction.started` / `compaction.completed`。
- `EventObserver` 是最小化的同步/异步兼容观察边界：`observe(event) -> object`。`Thread.astream` 在 yield 前调用 `self.observer.observe(event)`（若返回 awaitable 则 await）。
- 观察路径位于不可变生命周期事件的下游，**从不控制调度或 provider 响应**；规范化、脱敏、span 关联、计数、日志、导出都属于后续可观测性章节。

## Codex 参考策略（Codex reference strategy）

Super Harness 研究**一个固定的 OpenAI Codex 修订版**后再实现等价运行时功能，绝不针对未指定的 `main` 分支开发。

- 固定提交记录在 `references/CODEX_PIN.md`：仓库 `https://github.com/openai/codex.git`，提交 `7c6eb0eef113ddc16ae5b207ac9add364b489798`（2026-08-25，主题 "Scope stop hooks for memory consolidation (#40587)"）。
- 参考以浅 Git 子模块保留在 `references/codex/`；校验：`git -C references/codex rev-parse HEAD` 应输出上述提交。
- 每个功能在实现前必须在 `docs/research/codex/` 写研究笔记，包含：检查过的 Codex 文件/测试、行为契约、不变量、移除的 OpenAI 耦合、Python 原生设计、要复现的测试。

与本章直接相关的研究笔记：

- `docs/research/codex/model-provider-and-streaming.md` —— 模型 provider 与流式（第 2 层契约、终态事件、重试预算）。
- `docs/research/codex/agent-runtime-thread-turn.md` —— Agent/Thread/Turn 编排（状态机、历史、事件、取消）。
- `docs/research/codex/README.md` —— 研究笔记总纲。

其余子系统笔记（供后续章节引用）：`tool-runtime-sandbox-approval.md`、`durable-thread-context-compaction.md`、`search-rag-vision.md`、`working-and-long-term-memory.md`、`skills-and-mcp.md`、`plugins-and-hooks.md`、`autonomous-multi-agent.md`、`deterministic-workflow.md`、`hybrid-orchestration.md`、`observability-and-hardening.md`、`cli-ecosystem-ux.md`、`release-cross-cutting.md`。

## 关键接口 / 类（Key interfaces & classes）

### `ModelProvider`（协议，`models/base.py`）

```python
@runtime_checkable
class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def capabilities(self) -> ModelCapabilities: ...
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...
    async def aclose(self) -> None: ...
```

运行时只依赖这个协议——`Agent`、`Thread` 均以 `ModelProvider` 为 provider 类型，从不 import provider SDK。

### `OpenAICompatibleProvider`（`models/openai_compatible.py`）

```python
OpenAICompatibleProvider(
    *, model: str, base_url: str,
    api_key: str | None = None, api_key_env: str | None = None,
    wire_api: WireAPI = WireAPI.CHAT_COMPLETIONS,
    timeout: float = 60.0, max_retries: int = 2, stream_max_retries: int = 1,
    client: httpx.AsyncClient | None = None,
    name: str = "openai_compatible",
    capabilities: ModelCapabilities | None = None,
)
```

- `WireAPI.CHAT_COMPLETIONS` 或 `WireAPI.RESPONSES` 决定端点是 `/chat/completions` 还是 `/responses`。
- 认证失败在**网络 I/O 之前**显式失败（`_credential()` 抛 `ModelError`，details 带 provider 与 credential_source，不含密钥本身）。
- 重试：`max_retries`（非流）+ `stream_max_retries`（流）；`_retryable` 只对传输错误、超时、429 与 ≥500 重试，4xx 与认证失败不重试；指数退避 `min(0.25 * 2**attempt + random()*0.05, 2.0)`。
- 可注入 `httpx.AsyncClient`（测试用确定性客户端）；`_owns_client` 决定 `aclose` 是否关闭它。

### `DeepSeekProvider`（`models/deepseek.py`）

```python
DeepSeekProvider(*, model="deepseek-v4-flash", api_key=None,
    base_url="https://api.deepseek.com",
    wire_api=WireAPI.CHAT_COMPLETIONS, timeout=60.0,
    max_retries=2, stream_max_retries=1, client=None)
```

- `api_key_env="DEEPSEEK_API_KEY"`，`name="deepseek"`，`capabilities` 声明 `wire_apis=("chat_completions", "responses")`。
- 覆写 `_message` 把 `developer` 映射为 `system`；覆写 `_payload` 把 `response_format` 放宽为 `json_object`。

### `FallbackProvider`（`models/fallback.py`）

```python
FallbackProvider(providers: Sequence[ModelProvider], *,
    policy: FallbackPolicy | None = None, observer: EventObserver | None = None)
@dataclass(frozen=True)
class FallbackPolicy:
    timeout: float = 60.0
    retry_if: RetryPredicate = _retryable_error   # ModelError / TimeoutError
```

- `capabilities` 是链上各 provider 能力的**交集**（含 `wire_apis` 求交）。
- 按序尝试；每个尝试受 `asyncio.timeout(policy.timeout)` 约束。
- 流模式：若某 provider 已产生**可见输出**（text/tool delta 或 completed）后再失败，抛 `ModelError("provider stream failed after visible output; fallback is unsafe")`，**不回退**。

### `Agent`（`agent.py`）

```python
Agent(provider: ModelProvider, *,
    instructions: str | None = None, tools: Iterable[Tool] = (),
    approval: ApprovalPolicy | None = None, hooks: HookRegistry | None = None,
    observer: EventObserver | None = None, max_model_steps: int = 8,
    context: Iterable[ContextFragment] = (), cwd: str | None = None,
    agents_loader: AgentsMdLoader | None = None, store: SQLiteThreadStore | None = None,
    compaction_threshold_chars: int = 100_000, persona: Persona | None = None)

Agent.thread() -> Thread
Agent.resume(thread_id: str) -> Thread          # 需要 store，否则 RuntimeError
Agent.fork(thread_id: str) -> Thread
async Agent.arun(input, *, tools=(), output_schema=None) -> ModelResponse
Agent.run(input, *, tools=(), output_schema=None) -> ModelResponse
Agent.astream(input, *, tools=(), output_schema=None) -> AsyncIterator[Event]
Agent.stream(input, *, tools=(), output_schema=None) -> Iterator[Event]
async Agent.aclose() -> None
```

`Agent` 是可配置的、创建**相互独立** Thread 的工厂；每个 Thread 共享 agent 的 provider、tool 注册表/执行器、hooks、observer，但拥有自己的历史与 Turn。

### `Thread`（`runtime/thread.py`）

```python
@dataclass(slots=True)
class Thread:
    provider: ModelProvider
    instructions: str | None = None
    tool_registry / tool_executor / max_model_steps: int = 8
    context: ContextAssembler
    store: SQLiteThreadStore | None = None
    archived: bool = False
    parent_thread_id / metadata / summaries
    compaction_threshold_chars: int = 100_000
    compaction_retain_messages: int = 8
    hooks / observer
    thread_id / created_at / updated_at
    messages: list[Message]          # 有序历史
    turns: list[Turn]                # 有序 Turn

    async astream(...) -> AsyncIterator[Event]
    async arun(...) -> ModelResponse
    stream(...) / run(...)           # 同步薄消费者
    start(...) -> TurnHandle
    async acompact(...) / compact(...) -> tuple[Event, Event]
    archive() / fork() / request_interrupt() / queue_steering()
    async aclose()
```

`Thread` 持有**单一活动 Turn** 约束：`_active_turn_id` 非空时再跑会抛 `RuntimeError("thread already has an active turn")`。

### `TurnHandle`（`runtime/handle.py`）

```python
TurnHandle(thread, input, *, tools=(), output_schema=None)
async events() -> AsyncIterator[Event]
async wait() -> ModelResponse
async steer(instruction: str) -> None   # 排队到下一个模型步检查点
def cancel() -> None
async interrupt() -> None                # request_interrupt + cancel
```

### 异常层次（`exceptions.py`）

```python
SuperHarnessError(Exception)   # message, correlation_id, details(只读)
├── ConfigError
├── ProviderError
│   ├── ModelError · RAGError · SearchError · VisionError
├── ToolError ├── ToolValidationError
├── SandboxError
├── ApprovalDenied
├── MCPError
├── SkillError · PluginError · HookError
├── WorkflowError · MultiAgentError
└── CancelledError   # 公共边界可见的规范化取消
```

## Python 原生重设计（Python-native redesign）

这是与 Codex（Rust）最根本的分野，逐条对应研究笔记：

- **协议而非 trait**。`ModelProvider` 是 `@runtime_checkable` 的 Python `Protocol`，任何符合形状的对象都可注入（测试里用 `RecordingProvider`）。
- **不可变 dataclass 替代 Rust struct**。`frozen=True` + `MappingProxyType` 提供值语义，杜绝 Rust 所有权模型本可防止的共享可变状态问题。
- **异步生成器替代 stream 迭代器**。`provider.stream` 是 `AsyncIterator[ModelStreamEvent]`，消费方取消即关闭底层 HTTP 流——用 Python 的生成器取消语义表达 Codex 的 stream drop 语义。
- **`asyncio` 原语替代显式线程/通道**。`asyncio.gather`（并行工具）、`asyncio.wait_for`（工具超时）、`asyncio.Semaphore`（工作流限流）、`asyncio.Condition`（自主代理等待）、`asyncio.create_task` + `asyncio.Queue`（TurnHandle 泵送）。
- **零供应商 SDK**。模型层只依赖 `httpx`；无 OpenAI SDK、无账号/会话状态。

## 有意差异（Intentional differences）

相比 Codex，Super Harness 有意做出的差异（都记录在研究笔记的 "Differences and extensions"）：

- **Chat Completions 作为一等线协议**——中国可用性驱动。
- **流终态硬性要求**。流必须在 `[DONE]` / `response.completed` 后成功；提前关闭视为协议失败并在流预算内重试（`stream_no_completed.rs` 的 Python 版）。
- **阶段划分**。Phase 1 先只规范化工具调用，工具执行属于 Phase 2；持久化/上下文属于 Phase 3。Codex 的对应能力在架构上更早耦合。
- **同步入口是薄消费者**，而非独立实现；且**禁止在活动事件循环内调用**。
- **中断与取消是两个终态**；`resume` 把未完成 Turn 显式标记 `INTERRUPTED` 而非静默完成。
- **不回退已可见输出的 provider**。
- **DeepSeek 适配层**（`developer`→`system`、`json_object` 放宽）。

## 失败模型（Failure model）

- **类型化异常**。所有公共失败通过 `SuperHarnessError` 子类表达，携带只读 `details`（脱敏的诊断元数据）与可选 `correlation_id`；消息不含密钥。
- **模型层失败**。`OpenAICompatibleProvider` 把传输/HTTP/解析错误规范化为 `ModelError`；认证失败在传输前抛；4xx/认证不重试，429/5xx/传输错误在预算内重试并退避。
- **流失败**。提前关闭 → `httpx.RemoteProtocolError` → 流预算内重试；流内每个模型步失败发 `model.failed` 事件后 re-raise，Turn 标记 `FAILED`。
- **工具失败不中断 Turn**。校验/审批/超时/执行错误以 `success=False` 的 `ToolResult` 返回，模型可恢复；`ToolError("tool loop exceeded ...")` 只在超过模型步预算时抛出。
- **超时**。provider 默认 60s；Fallback 每个尝试 `asyncio.timeout`；工具各自 `timeout`。
- **取消**。`asyncio.CancelledError` 原样向上传播（`ToolExecutor` 与 `Thread` 都显式 `raise`），不会把任务取消误当作工具失败。
- **同步 API 误用**。活动事件循环内调用同步入口抛 `RuntimeError`。

## 扩展点（Extension points）

- **新模型/服务**：实现 `ModelProvider` 协议即可；`OpenAICompatibleProvider` 子类化或新写适配器，声明 `capabilities` 与 `wire_apis`。
- **provider 链**：用 `FallbackProvider` 组合多个 provider；能力声明取交集。
- **工具**：`Tool` / `@tool` 装饰器、`ToolRegistry`、`ToolExecutor`（审批、钩子、超时、输出上限均可扩展）。
- **钩子**：`HookRegistry` 在 session/prompt/turn/model/tool/compaction 各点分发（见后续插件与钩子章节）。
- **观察**：实现 `EventObserver` 挂到 `Agent(observer=...)`。
- **持久化**：`SQLiteThreadStore` 可替换（`Agent.store`）。
- **上下文**：`ContextFragment` / `ContextAssembler` 可注入；`AgentsMdLoader` 加载项目 AGENTS 文件。

## 测试（Tests）

与本章直接对应的测试文件（`tests/`）：

- `test_agent_runtime.py` —— Agent/Thread/Turn 生命周期、历史累积、生命周期事件、取消、同步 API 事件循环约束、工具循环与模型步预算。
- `test_openai_compatible.py` —— 两种线协议负载/解析、DeepSeek 默认与能力、工具与严格 schema 保留、重试预算、认证失败。
- `test_model_types.py` —— 不可变值防御性冻结、工具名约束、JSON 校验。
- `test_events.py` —— 事件不可变性与字段。
- `test_exceptions.py` —— 异常层次与脱敏 details。
- `test_provider_http_integration.py` —— 真实 HTTP 传输下的 provider 行为。
- `test_deepseek_e2e.py` —— DeepSeek 端到端（需凭据）。
- `test_context_and_persistence.py` —— 上下文组装/压缩与 SQLite 快照、resume/fork/archive。
- `test_config.py`、`test_package.py` —— 配置解析与包表面。

测试驱动开发遵循 `docs/research/codex/*.md` 中"Tests to reproduce"清单（如 `stream_no_completed`、`json_result` 的 Python 复现）。

## 限制与未来工作（Limitations / future work）

- **本地沙箱无法约束任意子进程系统调用**；Shell/Python 在非完全访问模式下禁用。完整隔离依赖 Docker 后端。
- **阶段 1 的历史为内存态**；跨进程状态恢复依赖持久化扩展。
- **同步 API 不允许在活动事件循环内使用**——这限制了某些混用场景（须用异步 API）。
- **不内置模型托管 / 向量库 / 进程隔离**——都是有意非目标。
- 未来方向：把中断/resume 的跨进程一致性做得更强、扩展 China-ready 服务适配器、细化 `EventObserver` 生态与 OTEL 导出。

相关章节：本章是 Internals 的骨架，后续章节逐一展开模型与流式、Tool、持久化、上下文与压缩、RAG、记忆、Skills/MCP、插件/钩子、自主编排、确定性工作流、可观测性与 CLI。用法见用户指南（`website/docs/guide/`）。
