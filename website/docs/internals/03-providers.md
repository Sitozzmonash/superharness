---
id: internals-03-providers
title: 模型 Provider 层与回退
sidebar_position: 3
description: ModelProvider 协议、中性请求/响应类型、OpenAI 兼容线路映射、DeepSeek 适配器、重试退避与显式回退链。
---

# 内部实现 #3：模型 Provider 层与回退

运行时对模型供应商的唯一依赖是一个精简的 `ModelProvider` 协议。它**绝不**依赖任何 provider SDK 的响应类：所有进出 provider 边界的数据都被建模为 `super_harness.models` 中的不可变中性值。本章深入这一层：协议本身、中性数据模型、`OpenAICompatibleProvider` 把中性值映射为 Chat Completions / Responses 两种 HTTP 线路、`DeepSeekProvider` 的默认适配、有界的重试退避，以及 `FallbackProvider` 提供的显式、可观测、不静默切换的回退链。

这一层回答的问题是"模型请求怎么被发送、怎么被解析、怎么在失败时被重试或切换"，而**不**回答"消息历史怎么编排、Turn 生命周期怎么管理、工具怎么执行"——那是 `Agent`/`Thread`/`Turn`（运行时期）的责任，属于其他 Internals 章节。

## 1. 职责

Provider 层位于"中性值"与"具体 HTTP 线路"之间，职责严格划分：

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `ModelProvider` | `models/base.py` | 运行时唯一依赖的异步协议：`name` / `capabilities` / `complete` / `stream` / `aclose` |
| 中性类型 | `models/types.py` | `Message`、`ToolDefinition`、`ToolCall`、`Usage`、`ModelCapabilities`、`ModelRequest`、`ModelResponse`、`ModelStreamEvent` 等不可变值 |
| `OpenAICompatibleProvider` | `models/openai_compatible.py` | 把中性值映射为 Chat Completions 或 Responses 的 HTTP 负载，并把回复/流事件映射回中性值；持有有界重试策略与 SSE 解析器 |
| `WireAPI` | `models/openai_compatible.py` | 两种线路枚举：`chat_completions` 与 `responses` |
| `DeepSeekProvider` | `models/deepseek.py` | DeepSeek 的 OpenAI 兼容适配：官方 base URL、`DEEPSEEK_API_KEY`、默认模型与能力声明、`developer→system` 角色映射、`json_object` 结构化输出 |
| `FallbackProvider` / `FallbackPolicy` | `models/fallback.py` | 显式的多 provider 回退链：按序尝试、每次有界超时、可观测、流式只在可见输出出现前回退 |
| 异常 | `exceptions.py` | `SuperHarnessError` → `ProviderError` → `ModelError` 的统一失败面 |

这一层明确**不负责**的事：

- 不做编排、不维护有序历史、不管理 Turn 状态机（那是 `Thread`/`Turn`）。
- 不执行工具、不做审批（那是 `ToolExecutor`）。
- 不持久化任何东西（provider 层无状态；Thread/Workflow 的持久化在别处）。
- 不做内容脱敏（脱敏发生在更下游的可观测性路径），但**错误元数据从不携带凭证**。

## 2. 数据模型

`super_harness.models` 中的类型全部是不可变值：`@dataclass(frozen=True, slots=True)`，所有 JSON 形状的字段在构造时被防御性地冻结成 `MappingProxyType`，因此请求、响应、工具调用与用量在任何地方（包括并发环境）都不会被意外改写。

### 2.1 消息与角色

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
```

`developer` 角色是中性请求的默认系统指令角色（`Thread._request` 把 `Agent.instructions` 组装为 `Message(MessageRole.DEVELOPER, ...)`）。它在发往 OpenAI 兼容服务时如何呈现由适配器决定——标准线路原样发送，DeepSeek 适配器把它映射为 `system`（见 §10）。

### 2.2 工具定义与工具调用

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: JsonObject          # Mapping[str, Any]（冻结）

@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: JsonObject           # 解析后的参数对象（冻结）
    raw_arguments: str              # 未经解析的原始参数字符串，用于逐字回传
```

构造时强校验：

- 工具名必须匹配 `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`（1–128 个安全字符），否则抛 `ValueError`。
- `ToolCall.call_id` 必须 1–256 字符且不含控制字符。
- `ToolCall.raw_arguments` 不得超过 1,000,000 字符。
- 所有 JSON 对象经过 `_validate_json`：嵌套深度 ≤ 32、不允许非有限浮点数（`nan`/`inf`）、不允许循环引用、对象键必须是字符串、字段/数组项数 ≤ 10,000。

`raw_arguments` 的存在是为了保证"工具调用参数逐字无损回传"：协议层解析成 `arguments` 供校验使用，同时保留原始字符串以便在后续请求中按原样塞回 `messages`（见 §3 与测试 `test_tool_history_maps_to_each_wire_format`）。

### 2.3 用量

```python
@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
```

`_usage` 在解析时把不同线路的字段名归一：`prompt_tokens`/`input_tokens` → `input_tokens`，`completion_tokens`/`output_tokens` → `output_tokens`，`total_tokens` 缺省时回退为两者之和。

### 2.4 能力声明

```python
@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    streaming: bool = True
    tools: bool = True
    structured_output: bool = True
    reasoning: bool = False
    parallel_tool_calls: bool = True
    wire_apis: tuple[str, ...] = ("chat_completions",)
```

能力声明让运行时在不试探的情况下知道"这条链支持什么"。`FallbackProvider.capabilities` 取整条链的**交集**（见 §11）。

### 2.5 请求与响应

```python
@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: Sequence[Message]
    tools: Sequence[ToolDefinition] = ()
    output_schema: JsonObject | None = None
    temperature: float | None = None
    parallel_tool_calls: bool = True
    extra: JsonObject = field(default_factory=_freeze)   # 透传给负载的额外键

@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    response_id: str | None = None
    finish_reason: str | None = None
    output_json: JsonObject | None = None
```

关键点：

- `output_schema` 是**可选的严格 JSON Schema**。设置后，适配器会请求结构化输出，且 `_structured` 在返回前把 `text` 解析为 `output_json`。
- `extra` 允许调用方注入 provider 特有的额外负载键，最后 `payload.update(request.extra)` 合并进请求体。
- `ModelResponse` 不引用任何 SDK 类型：纯 `str` / `tuple` / `Usage` / `JsonObject`。

### 2.6 流事件

```python
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

流路径是权威路径（见 §3）。事件序列的契约是：

```
STARTED → (TEXT_DELTA | TOOL_CALL_DELTA)* → COMPLETED(response=ModelResponse)
```

`COMPLETED` 事件携带最终归一化的 `ModelResponse`。`TOOL_CALL_DELTA` 携带累积的工具调用身份（`tool_call_index`、`tool_call_id`、`tool_name`）与本次 `delta`。

## 3. 生命周期

### 3.1 构造与 HTTP 客户端

`OpenAICompatibleProvider` 在构造时不发起任何网络 I/O。HTTP 客户端是**惰性**创建的：

```python
def _http(self) -> httpx.AsyncClient:
    if self._client is None:
        self._client = httpx.AsyncClient(timeout=self.timeout)
    return self._client
```

- `timeout` 默认 60.0 秒，作为 `httpx.AsyncClient(timeout=...)` 的总体超时。
- 可以注入一个外部 `httpx.AsyncClient`（用于确定性测试，例如 `httpx.MockTransport` 或本地 `ThreadingHTTPServer`）；注入时 `_owns_client=False`，`aclose()` 不会关闭它。

### 3.2 `complete()` 时序

非流式路径：

```
调用方                    OpenAICompatibleProvider            httpx.AsyncClient
  |  complete(request)           |                                  |
  |----------------------------->|  _credential()  环境变量或显式 api_key
  |                              |  _endpoint()    /chat/completions 或 /responses
  |                              |  _payload(request, stream=False)
  |                              |  _headers()     Authorization: Bearer <key>
  |                              |--------------------------------->|  POST
  |                              |<---------------------------------|  200 JSON
  |                              |  _normalize(data)  按 wire 解析
  |                              |  _structured(...)  解析 text → output_json
  |<-----------------------------|  ModelResponse
```

`complete()` 的重试循环（`max_retries` 默认 2，即最多 3 次 POST 尝试）包裹上面的主体，详见 §11。

### 3.3 `stream()` 时序与权威终点

```
调用方                OpenAICompatibleProvider               httpx.AsyncClient
  |  stream(request)       |                                  |
  |----------------------->|  yield STARTED                   |
  |                        |  _stream_once(...)  (流预算内可重试)
  |                        |--------------------------------->|  POST stream=True
  |<-----------------------|  TEXT_DELTA / TOOL_CALL_DELTA    |  SSE: data: {...}
  |                        |    （在内存累加 text / tool_call 状态）
  |                        |<---------------------------------|  data: [DONE]
  |                        |    或 Responses response.completed
  |                        |  组装 ToolCall / Usage / output_json
  |<-----------------------|  COMPLETED(response=result)
```

流是否成功取决于**终端完成事件**：

- Chat Completions 只有在读到 `data: [DONE]` 之后才算成功。
- Responses 只有在读到 `type: "response.completed"` 之后才算成功。

如果 HTTP 响应提前关闭而从未出现终端事件，`_stream_once` 抛 `httpx.RemoteProtocolError("stream closed before terminal completion event")`。这是**可重试的协议失败**，会在配置的流预算内（`stream_max_retries` 默认 1，即最多 2 次流尝试）重试。测试 `test_incomplete_stream_is_an_error` 验证了这一点。

### 3.4 `aclose()` 与关闭

```python
async def aclose(self) -> None:
    if self._client is not None and self._owns_client:
        await self._client.aclose()
    self._client = None
```

只有 provider 自建的客户端才被关闭；注入的客户端由调用方负责。

### 3.5 运行期如何消费（权威流路径）

`Thread._astream_unobserved` **只调用 `self.provider.stream(request)`**，从不调用 `complete()`——流是权威路径。它把中性流事件映射为运行期事件（见 §7）。这意味着即使是一个只实现了 `complete()` 的简化 provider，运行时也只会走流路径；因此任何想被运行时驱动的 provider 都必须实现 `stream()`。

## 4. 关键接口 / 类

### 4.1 协议：`ModelProvider`

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

注意 `stream` 是**同步返回 async 生成器**的方法（`def stream(...) -> AsyncIterator[...]`），而不是 `async def`。这是故意的：让调用方在拿到生成器前不需要额外 `await`，且生成器体内可以 `yield STARTED` 作为首个事件。协议是 `@runtime_checkable`，因此可以用 `isinstance` 做鸭子类型检查。

### 4.2 线路枚举：`WireAPI`

```python
class WireAPI(StrEnum):
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"
```

### 4.3 适配器：`OpenAICompatibleProvider`

构造签名（全部关键字参数）：

```python
OpenAICompatibleProvider(
    *,
    model: str,                       # 必填
    base_url: str,                    # 必填
    api_key: str | None = None,
    api_key_env: str | None = None,
    wire_api: WireAPI = WireAPI.CHAT_COMPLETIONS,
    timeout: float = 60.0,
    max_retries: int = 2,
    stream_max_retries: int = 1,
    client: httpx.AsyncClient | None = None,
    name: str = "openai_compatible",
    capabilities: ModelCapabilities | None = None,
)
```

公共属性/方法：`name`、`capabilities`、`model`、`base_url`、`wire_api`、`timeout`、`max_retries`、`stream_max_retries`、`complete`、`stream`、`aclose`。内部关键钩子（子类可重写，DeepSeek 正是这么做的）：

```python
_message(message: Message) -> dict          # 中性消息 → 线路消息
_payload(request, *, stream) -> dict        # 中性请求 → HTTP 负载
_responses_inputs(messages) -> list[dict]   # 中性消息 → Responses input 项
_normalize(data) -> ModelResponse           # 线路响应 → 中性响应
_structured(response, request) -> ModelResponse  # text → output_json
_retryable(exc) -> bool                     # 该异常是否可重试
_error(exc) -> ModelError                   # 归一化错误
_credential() -> str                        # 取凭证（缺失即抛）
_endpoint() -> str                          # 拼 URL
```

### 4.4 默认适配：`DeepSeekProvider`

```python
DeepSeekProvider(
    *,
    model: str = "deepseek-v4-flash",
    api_key: str | None = None,
    base_url: str = "https://api.deepseek.com",
    wire_api: WireAPI = WireAPI.CHAT_COMPLETIONS,
    timeout: float = 60.0,
    max_retries: int = 2,
    stream_max_retries: int = 1,
    client: httpx.AsyncClient | None = None,
)
```

它继承 `OpenAICompatibleProvider`，只覆盖三点：

1. 默认模型 `deepseek-v4-flash`、官方 base URL、`api_key_env="DEEPSEEK_API_KEY"`、`name="deepseek"`。
2. 能力声明同时声明两条线路：`wire_apis=("chat_completions", "responses")`，并声明 `reasoning=True`。
3. 重写 `_message`（`developer → system`）与 `_payload`（结构化输出改用 `json_object`）。

### 4.5 回退：`FallbackProvider` 与 `FallbackPolicy`

```python
RetryPredicate = Callable[[Exception], bool]

@dataclass(frozen=True, slots=True)
class FallbackPolicy:
    timeout: float = 60.0
    retry_if: RetryPredicate = _retryable_error   # 默认: isinstance(error, (ModelError, TimeoutError))

FallbackProvider(
    providers: Sequence[ModelProvider],
    *,
    policy: FallbackPolicy | None = None,
    observer: EventObserver | None = None,
)
```

`FallbackProvider.name` 返回 `"fallback[" + ",".join(各 provider 名) + "]"`；`model` 属性取链上第一个 provider 的 `model`（供运行期事件读取）。

## 5. 并发 / 取消

- **共享客户端**：每个 provider 持有单个 `httpx.AsyncClient`，`httpx.AsyncClient` 是线程安全的，因此同一 provider 可安全地并发发起多个 `complete`/`stream`。
- **取消通过异步生成器传播**：`stream()` 是 async 生成器，调用方停止迭代（如 `async for` 中断、`aclosing` 或任务取消）时，HTTPX 会关闭对应的 HTTP 响应流，底层连接随之释放。`httpx` 的 `stream()` 上下文管理器在生成器被关闭/取消时正确地关闭响应。
- **运行时对取消不归一化**：`Thread._astream_unobserved` 中 `except asyncio.CancelledError: raise`，把取消原样向上抛，绝不把它包装成 `ModelError` 或 `TurnStatus.FAILED`。任务取消是一种**终止状态**（`TurnStatus.CANCELLED`），与失败（`FAILED`）或中断（`INTERRUPTED`）区分。
- **Fallback 不吞取消**：`FallbackProvider.complete`/`stream` 的 `except Exception` 只捕获普通异常；`asyncio.CancelledError` 继承自 `BaseException`，不被捕获，`asyncio.timeout` 上下文会把取消传播给正在执行的子 provider。测试 `test_fallback_timeout_and_cancellation_are_distinct` 验证了"超时导致回退、取消直接抛 `asyncio.CancelledError`"的区分。

## 6. 持久化（不适用）

Provider 层**无持久化状态**：不写数据库、不缓存、不维护跨请求状态。凭证来自构造参数或环境变量（每次请求经 `_credential()` 读取）；HTTP 客户端是进程内资源，随 `aclose()` 释放。Thread 元数据、有序消息、Turn 等需要持久化的东西在运行期由 `SQLiteThreadStore` 负责（见对应 Internals 章节），provider 对这些一无所知，因此持久化可以随意替换而不影响本层。

## 7. 事件 / 可观测性

### 7.1 Fallback 链自己的事件

`FallbackProvider` 接受可选的 `EventObserver`（`runtime/events.py` 中的最小协议，`observe(event) -> object`，返回值可为可等待对象，会被 `await`）。它按序发出四个事件类型，payload 从不含凭证：

| 事件类型 | payload 键 | 触发时机 |
| --- | --- | --- |
| `provider.attempt.started` | `provider`, `attempt`(1-based) | 每次尝试开始 |
| `provider.attempt.completed` | `provider`, `attempt` | 某次尝试成功返回 |
| `provider.attempt.failed` | `provider`, `attempt`, `error_class` | 某次尝试抛出异常 |
| `provider.fallback.selected` | `provider`(下一个), `attempt`, `previous_provider` | 决定回退到下一个 provider |

测试 `test_fallback_complete_is_observable_and_ordered` 断言完整事件序列为：`attempt.started → attempt.failed → fallback.selected → attempt.started → attempt.completed`。

### 7.2 运行期对 provider 流事件的重映射

`Thread` 把中性流事件映射为关联了 `thread_id`/`turn_id`/`step` 的运行期事件：

| 中性事件 | 运行期事件 | payload |
| --- | --- | --- |
| `STARTED` | `model.started` | `provider`, `model`, `step` |
| `TEXT_DELTA` | `model.text.delta` | `delta`, `step` |
| `TOOL_CALL_DELTA` | `model.tool_call.delta` | `index`, `name`, `delta`, `step`（并设置 `tool_call_id` 关联字段） |
| `COMPLETED` | `model.completed` | `response`, `usage`, `tool_calls`, `provider`, `model`, `step` |
| （流抛异常） | `model.failed` | `provider`, `model`, `step`, `error_class`, `message` |

`model.completed` 是运行期累积模型用量与工具调用的来源（`AgentManager` 从每个 `model.completed` 事件累加 usage）。`provider` 取 `self.provider.name`，`model` 取 `getattr(self.provider, "model", None)`，因此 `FallbackProvider` 的 `name`（形如 `fallback[a,b]`）会出现在事件里，`model` 取链首 provider 的模型名。

## 8. Codex 参考

本层的设计依据记录在 `docs/research/codex/model-provider-and-streaming.md`。其检查的 Codex（Rust）源文件包括：

- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/model-provider/src/provider.rs`
- `codex-rs/codex-api/src/common.rs`
- `codex-rs/core/src/client_common.rs`
- `codex-rs/core/src/client.rs`
- `codex-rs/protocol/src/models.rs`

其记录的**行为契约**（被本层逐条实现）：

- 一个 provider 描述其端点、认证来源、线路协议、能力、重试上限与流空闲超时。
- 请求携带归一化的消息、工具、并行工具偏好与可选的严格 JSON Schema。
- 流式产生结构化的生命周期、增量、条目、用量与终止事件。
- 在终止完成事件之前关闭的流是错误，可消耗有界的流重试预算。
- 认证错误是显式的；缺失或空白的凭证环境变量在网络 I/O 之前失败。
- 丢弃或取消一个流会取消其下游工作。

其记录的**不变量**（被本层保持）：

- 重试次数与超时是有界的。
- 认证失败与非法请求不重试。
- provider 响应对象不逃逸 provider 边界。
- 工具调用保留 provider 的调用 ID 与参数。
- JSON Schema 无损耗地传输（不做有损重写）。
- 成功的流式必须出现终止完成事件。

关于相关运行期章节（Agent/Thread/Turn 编排），可参考 `docs/research/codex/agent-runtime-thread-turn.md`。

## 9. Python 原生重设计

把 Codex 的 Rust 设计移植到 Python 时做了如下映射：

- **`provider-info` 结构 → `ModelCapabilities` + 构造参数**：端点、认证来源、线路、超时、重试上限都从协议/构造器声明，能力以 `ModelCapabilities` 显式声明。
- **Rust trait/provider → 异步 `Protocol`**：`ModelProvider` 是 `@runtime_checkable` 的 `typing.Protocol`，鸭子类型即可实现，不需要继承。
- **不可变请求/响应值 → `@dataclass(frozen=True, slots=True)` + `MappingProxyType` 冻结**：保证并发与多步工具循环下请求/响应不被改写。
- **显式 bearer 认证 → `_credential()` 预检**：在任何网络 I/O 之前检查凭证，缺失即抛 `ModelError`（见测试 `test_missing_credential_fails_before_transport`）。
- **流式结构化事件 → `ModelStreamEvent` 枚举**：`STARTED/TEXT_DELTA/TOOL_CALL_DELTA/COMPLETED` 与 Codex 的"生命周期、增量、项、用量、终止"一一对应。
- **终止完成事件要求 → `[DONE]`/`response.completed` 门控**：提前关闭是可重试协议错误。
- **去掉 OpenAI SDK 耦合**：本层不依赖 OpenAI 的认证管理器、账户状态、ChatGPT 头、prompt-cache 标识符或 OpenAI SDK 响应类。Chat Completions 与 Responses 都是同一个 provider 中性协议背后的线路适配器。

## 10. 有意差异

- **Chat Completions 是一等线路**：因为它是中国境内大量 OpenAI 兼容服务广泛支持的格式，所以被作为默认线路（`WireAPI.CHAT_COMPLETIONS`）而非二等兼容。
- **DeepSeek `developer → system` 映射**：DeepSeek 原生 API 拒绝 OpenAI 的 `developer` 角色、要求 `system`；`DeepSeekProvider._message` 只做这一处改写，其余 OpenAI 兼容复用保持字节一致。
- **DeepSeek 结构化输出用 `json_object` 而非 `json_schema`**：DeepSeek 原生 API 对 `response_format: json_schema` 返回 `"This response_format type is unavailable now"`，只接受 `json_object`。因为 `_structured` 会在解析后**本地校验** schema 一致性（把 `text` 解析为 `output_json`），所以放宽成 `json_object` 是安全的。
- **错误元数据从不携带凭证**：归一化的 `ModelError.details` 只含 `provider` 与 `status_code` 等，绝不含请求密钥。
- **provider 拥有自己的 HTTP 客户端生命周期，也接受注入**：注入客户端使确定性测试（`httpx.MockTransport`、本地 HTTP 服务器）成为可能。
- **回退是显式、可观测的**：`FallbackProvider` 不是静默地"悄悄换 provider"，而是按序尝试、发出事件，且在流式已产生可见输出后**拒绝**回退（见 §11）。
- **取消不被归一化**：任务取消始终以 `asyncio.CancelledError` 传播，绝不包装成失败。

## 11. 失败模型

### 11.1 异常层级

```
SuperHarnessError
└── ProviderError
    └── ModelError
```

`ModelError` 携带 `message`（无密钥的人类可读描述）、`correlation_id`、`details`（只读 `MappingProxyType` 的脱敏诊断元数据）。

### 11.2 凭证失败

`_credential()` 优先用显式 `api_key`，否则读 `api_key_env` 环境变量；缺失或空白时**在网络 I/O 之前**抛 `ModelError`：

```
missing credential for provider deepseek: set DEEPSEEK_API_KEY
```

`details={"provider": ..., "credential_source": ...}`。凭证失败不可重试。

### 11.3 可重试性判定与有界退避

`OpenAICompatibleProvider._retryable(exc)`：

| 异常 | 可重试？ |
| --- | --- |
| `httpx.TransportError`（含 `RemoteProtocolError`、连接错误） | ✅ |
| `httpx.TimeoutException` | ✅ |
| `httpx.HTTPStatusError` 且状态为 `429` 或 `>= 500` | ✅ |
| 其余 `HTTPStatusError`（4xx、401、403 等） | ❌ |
| `ModelError`（解析/结构化失败） | ❌（直接重抛） |
| 非法 JSON / `ValueError` | ❌ |

退避公式（`_backoff`）：

```python
await asyncio.sleep(min(0.25 * (2 ** attempt) + random.random() * 0.05, 2.0))
```

指数退避、带小幅随机抖动、封顶 2.0 秒。预算有界：非流式 `max_retries`（默认 2 → 最多 3 次 POST），流式 `stream_max_retries`（默认 1 → 最多 2 次流尝试）。

### 11.4 回退链

`FallbackProvider` 的失败模型由 `FallbackPolicy` 控制：

- **每次尝试有界超时**：`asyncio.timeout(self.policy.timeout)`（默认 60.0s），超时抛 `TimeoutError`。
- **`retry_if` 谓词**：默认 `_retryable_error`，即 `isinstance(error, (ModelError, TimeoutError))`。注意它作用于**原始异常**：provider 内的传输/429/5xx 已被适配器归一化成 `ModelError`，因此可回退；而一个意料之外的编程错误（如 `ValueError`）不可回退，`backup` 不会被使用（见 `test_fallback_does_not_hide_unexpected_provider_bug`）。
- **错误归一化**：`ModelError` 原样；`TimeoutError` → `ModelError("model provider attempt timed out", details={provider, timeout})`；其它 → `ModelError("model provider attempt failed", details={provider, error_class})`。
- **链耗尽**：所有 provider 都失败时抛 `ModelError("provider fallback exhausted", details={"attempts": [{"provider", "error"}...]})`。

**流式回退的安全门**（`stream`）：`FallbackProvider` 跟踪 `visible`——一旦出现 `TEXT_DELTA`/`TOOL_CALL_DELTA`/`COMPLETED` 就置位。若某 provider 在产生可见输出后才失败，回退被视为不安全：

```
provider stream failed after visible output; fallback is unsafe
```

此时**不**切换到下一个 provider，直接抛 `ModelError`（见 `test_fallback_stream_before_output_and_never_after_visible_output`）。若失败发生在任何可见输出之前，则允许回退到下一个 provider。流式回退只发生在"输出开始之前"，避免用户看到一半答案突然被替换。

### 11.5 三个可运行示例

**基础：显式失败后回退**（[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/81_provider_fallback.py)）：

```python
"""Fall back after an explicit provider failure."""
import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackProvider
from super_harness.exceptions import ModelError
from super_harness.models import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class Provider:
    capabilities = ModelCapabilities()

    def __init__(self, name: str, answer: str = "") -> None:
        self.name, self.answer = name, answer

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if not self.answer:
            raise ModelError("unavailable")
        return ModelResponse(text=self.answer)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


print(asyncio.run(FallbackProvider((Provider("primary"), Provider("backup", "ok"))).complete(ModelRequest(()))).text)
```

**真实场景：只在首 provider 未产生可见输出时从 backup 流式输出**（[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/82_stream_fallback_safety.py)）：

```python
"""Stream from a backup only when the first provider emitted no visible output."""
import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackProvider
from super_harness.exceptions import ModelError
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class StreamProvider:
    capabilities = ModelCapabilities()

    def __init__(self, name: str, fail: bool) -> None:
        self.name, self.fail = name, fail

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if self.fail:
            raise ModelError("before output")
        response = ModelResponse(text="safe")
        yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta="safe")
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=response)

    async def aclose(self) -> None:
        pass


async def main() -> None:
    provider = FallbackProvider((StreamProvider("primary", True), StreamProvider("backup", False)))
    print([event.type async for event in provider.stream(ModelRequest(()))])


asyncio.run(main())
```

**进阶/组合：每次尝试的有界超时**（[查看完整可运行示例](https://github.com/Sitozzmonash/superharness/blob/main/examples/83_fallback_timeout.py)）：

```python
"""Apply a bounded timeout per provider attempt."""
import asyncio
from collections.abc import AsyncIterator

from super_harness import FallbackPolicy, FallbackProvider
from super_harness.models import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class SlowProvider:
    name = "slow"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        await asyncio.sleep(10)
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass


async def main() -> None:
    try:
        await FallbackProvider((SlowProvider(),), policy=FallbackPolicy(timeout=0.01)).complete(ModelRequest(()))
    except Exception as error:
        print(type(error).__name__, str(error))


asyncio.run(main())
```

## 12. 扩展点

1. **实现 `ModelProvider` 协议**：任何带 `name`/`capabilities`/`complete`/`stream`/`aclose` 的对象都可作为 provider 传入 `Agent(...)` 或 `FallbackProvider(...)`。协议是 `@runtime_checkable`，鸭子类型即可。
2. **注入 `httpx.AsyncClient`**：用 `httpx.MockTransport` 或本地 `ThreadingHTTPServer` 做确定性/集成测试；provider 只关闭自己创建的客户端。
3. **子类化 `OpenAICompatibleProvider`**：像 `DeepSeekProvider` 一样重写 `_message`/`_payload` 以适配供应商的怪癖（角色映射、结构化输出格式、额外头部/字段），其余逻辑免费复用。
4. **`WireAPI` 选择**：对任意 OpenAI 兼容端点，用 `wire_api=WireAPI.RESPONSES` 或 `CHAT_COMPLETIONS` 选择线路。
5. **自定义 `FallbackPolicy.retry_if`**：替换默认的"`ModelError`/`TimeoutError`"谓词，实现按异常类型定制的回退条件。
6. **注入 `EventObserver`**：订阅 `provider.attempt.*` / `provider.fallback.selected` 事件，接入既有观测管道。
7. **`ModelRequest.extra`**：注入 provider 特有的请求负载键而不改动适配器代码。

## 13. 测试

Provider 层由四组测试覆盖：

**`tests/test_openai_compatible.py`** —— 适配器与线路映射：

| 测试 | 验证点 |
| --- | --- |
| `test_deepseek_defaults_and_capabilities` | DeepSeek 默认模型、base URL、双线路能力声明 |
| `test_missing_credential_fails_before_transport` | 缺失凭证在传输前抛 `ModelError`，网络不被调用 |
| `test_chat_payload_and_tool_call_normalization` | Chat 负载保留 strict schema 与 tools；工具调用归一化为中性 `ToolCall`；usage 归一化 |
| `test_responses_payload_and_response_normalization` | Responses 负载 `text.format`；`output_json` 解析；usage 归一化 |
| `test_tool_history_maps_to_each_wire_format` | 同一工具历史映射为 `function_call` + `function_call_output`（Responses） |
| `test_responses_stream_normalizes_text_tool_and_json` | Responses SSE 增量组装成单一响应并需要 `response.completed` |
| `test_retry_is_bounded_and_only_for_retryable_status` | 500 在预算内重试、最终成功；尝试次数有界 |
| `test_chat_stream_requires_done_and_normalizes_tool_deltas` | Chat 流增量按 index 累加工具调用，需要 `[DONE]` |
| `test_incomplete_stream_is_an_error` | 提前关闭的流是错误 |

**`tests/test_model_types.py`** —— 数据模型：

| 测试 | 验证点 |
| --- | --- |
| `test_request_defensively_freezes_inputs` | 构造时冻结 `output_schema`/`tools`，改原始 dict 不影响请求 |
| `test_messages_are_immutable` | 消息不可变（`FrozenInstanceError`） |
| `test_tool_name_must_be_non_empty` | 非法工具名抛 `ValueError` |

**`tests/test_provider_http_integration.py`** —— 真实本地 HTTP 集成（`@pytest.mark.integration`，用 `ThreadingHTTPServer`）：

- `test_complete_and_stream_over_real_local_http`：对真实本地端点做 `complete` + `stream`，并驱动完整 `Agent`/`Thread` 运行时；断言最终 `ModelResponse.text == "local stream"`、`usage.total_tokens == 4`、收到 3 个请求。
- `test_agent_tool_loop_over_real_local_http`：用真实本地 SSE 端点跑完整个工具循环（assistant `tool_calls` → `tool` 结果 → 最终 `42`），断言第二个请求的 `messages` 角色序列为 `["user", "assistant", "tool"]` 且 `tool_call_id` 正确。

**`tests/test_release_crosscutting.py`** —— 回退链：

| 测试 | 验证点 |
| --- | --- |
| `test_fallback_complete_is_observable_and_ordered` | `complete` 可观测且按序；事件序列精确匹配；`aclose` 关闭所有 provider |
| `test_fallback_stream_before_output_and_never_after_visible_output` | 输出前可回退；可见输出后回退不安全、`backup` 不被调用 |
| `test_fallback_timeout_and_cancellation_are_distinct` | 超时导致回退到 backup；任务取消以 `asyncio.CancelledError` 传播 |
| `test_fallback_does_not_hide_unexpected_provider_bug` | 非 `retry_if` 的异常（编程 bug）不隐藏、不触发 backup |

## 14. 限制 / 未来工作

- **无独立的流空闲超时**：Codex 记录"stream idle timeout"，而当前 Python 实现用 `httpx.AsyncClient(timeout=...)` 的总体超时；尚未暴露单独的"停滞流"空闲定时器。未来可为 SSE 读取间隔增加显式空闲超时。
- **DeepSeek 结构化输出是本地保障**：服务端收到的是 `json_object` 而非严格 `json_schema`，schema 一致性依赖本地 `_structured` 解析。若想获得服务端强校验，需等待 DeepSeek 原生支持 `json_schema`。
- **回退是线性顺序，无健康/负载感知**：`FallbackProvider` 只按声明顺序尝试，不做基于延迟、成功率或熔断的路由；也不按预算（如 token 预算）选择 provider。
- **无 SDK/原生后端**：本层只做 HTTP（OpenAI 兼容线路）；不提供 gRPC 或官方 SDK 适配器。
- **usage 可能为零直到终止事件**：Chat Completions 的 usage 通常出现在最后的 chunk；若中间 chunk 未携带 usage 且无终止 usage，则 `Usage` 保持默认值。结构化流 (`_stream_once`) 以终止事件的 usage 为准。
- **`output_json` 仅在设置 `output_schema` 时填充**：纯工具调用响应 `text` 为空、`tool_calls` 非空，`output_json` 为 `None`。
- **`parallel_tool_calls` 是声明而非强约束**：能力与请求都声明了并行工具调用，但实际是否并行取决于 provider 端实现。
- **`complete()` 对 provider 是"权威"补充，但运行时只走 `stream()`**：运行时只消费流路径，因此 `complete()` 只对直接调用它的用户/工具有价值；未来可考虑让运行时在非流场景也走 `complete()` 以省去 SSE 开销。
