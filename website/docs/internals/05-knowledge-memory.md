---
id: internals-05-knowledge-memory
title: 第 5 章 外部知识管道与记忆
sidebar_position: 5
description: KnowledgeRouter 与 WebSearch/RAG/Vision 异步协议、记忆流水线（WorkingMemory、SQLiteMemoryStore、MemoryManager）的内部原理。
---

# 第 5 章 外部知识管道与记忆

本章解释 `super_harness.knowledge` 与 `super_harness.memory` 两个子系统的内部工作原理：外部知识（联网搜索、RAG 检索、视觉分析）如何穿过统一的异步协议、被规范化为不可变中性值、注入上下文并暴露为模型可见工具；以及短期记忆（Thread 消息、`WorkingMemory`）与长期记忆（`SQLiteMemoryStore`、`MemoryManager`）如何分层协作。相关实现位于：

- `src/super_harness/knowledge/` — `types.py`、`providers.py`、`routing.py`
- `src/super_harness/memory/` — `types.py`、`working.py`、`store.py`、`pipeline.py`

本章回答"怎么工作、为何这样设计"；如何配置与调用这些能力见对应的指南页面。

## 1. 职责（Responsibilities）

### 1.1 KnowledgeRouter 的边界

`KnowledgeRouter` 是运行时与外部知识世界之间的唯一门面。它持有三个可选的异步 provider（`WebSearchProvider`、`RAGProvider`、`VisionProvider`），并承担四类职责：

1. **直通调用**：把 `search` / `retrieve` / `vision` 转发给已配置的 provider；未配置时抛出明确的 `RuntimeError`，而不是静默返回空结果。
2. **上下文注入**：把中性结果转换为 `ContextKind.RAG` 标记的 `ContextFragment`（`rag_context` / `search_context`），这些片段以用户角色（`MessageRole.USER`）渲染，只有数据权威、没有指令权威。
3. **工具暴露**：把每个已配置的 provider 包装成 `knowledge` 命名空间下、`source="provider"` 的普通 `Tool`（`web_search`、`rag_retrieve`、`vision_analyze`），复用整套 Tool 校验/审批/超时/结果规范化流水线。
4. **失败与可观测边界**：所有远端失败被规范化为 `SearchError` / `RAGError` / `VisionError`，通过 `KnowledgeTrace` 汇与 `Event` 观察口发出，但凭证与图像体永不进入这些通道。

`KnowledgeRouter` 不拥有任何 provider 生命周期，也不持有 HTTP 客户端；它只是把三种协议收敛到一个 Python 对象上，让应用层可以只依赖一个门面。

### 1.2 记忆的三层职责

记忆按时效与持久性分成三层，各司其职：

| 层 | 实现 | 生命周期 | 职责 |
|---|---|---|---|
| 会话记忆 | `Thread.messages` | 随 Thread 持久化 | 当前会话的完整消息历史，即时上下文 |
| 工作记忆 | `WorkingMemory` | 进程内、有界 LRU | 跨模型步、跨工具调用的应用级键值状态 |
| 长期记忆 | `SQLiteMemoryStore` + `MemoryManager` | SQLite 文件，跨进程/重启 | 跨 Thread 的规范化事实沉淀与按需检索 |

`MemoryManager` 编排长期记忆流水线：**可替换的提取器**（extractor）→ 候选（`MemoryCandidate`）→ 规范化 upsert 到 store → 排名检索（ranked retrieval）→ 转换为 `ContextKind.MEMORY` 片段。内置的 `HeuristicMemoryExtractor` 只认显式的 `Remember:` / `Memory:` 行，绝不凭空发明用户事实——这是"提取保守、宁缺毋滥"的刻意设计。

## 2. 数据模型（Data model）

### 2.1 知识层的不可变中性值（`knowledge/types.py`）

所有值都是 `@dataclass(frozen=True, slots=True)`，`metadata` 在 `__post_init__` 里通过 `MappingProxyType(dict(...))` 冻结为只读映射。provider 特有的响应形态在适配器内部被消化掉，运行时只见这些中性值：

```python
@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    results: tuple[SearchResult, ...]   # 已按 top_n 截断
    provider: str                        # 归一化 provider 名，如 "zhipu"

@dataclass(frozen=True, slots=True)
class RAGDocument:
    text: str                            # 构造时校验非空白，否则 ValueError
    score: float | None = None
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

@dataclass(frozen=True, slots=True)
class VisionResult:
    text: str
    model: str
    provider: str

@dataclass(frozen=True, slots=True)
class KnowledgeTrace:
    operation: str    # "search" | "retrieve" | "vision"
    provider: str
    success: bool
    item_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
```

要点：

- `SearchResponse.results` 与 `RAGProvider.retrieve` 的返回值都是**元组**（不可变）；`HTTPRAGProvider` 返回 `tuple[RAGDocument, ...]`。
- `KnowledgeTrace` 是唯一外发的可观测载荷：只含操作名、provider、成功标志、条目数与脱敏元数据。**不含查询原文、不含 API key、不含图像体**（`ZhipuVisionProvider` 的 trace 元数据只放 `{"model": ...}`）。
- `RAGDocument` 在构造时拒绝空文本，把"畸形响应"从数据层提前挡掉。

### 2.2 异步 provider 协议（`providers.py`）

三个 `Protocol` 加起来只有三个方法，是适配器必须满足的鸭子类型契约：

```python
class WebSearchProvider(Protocol):
    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse: ...

class RAGProvider(Protocol):
    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]: ...

class VisionProvider(Protocol):
    async def analyze(self, image: str | Path, prompt: str) -> VisionResult: ...
```

`TraceSink` 与观察口刻意兼容同步与异步两种回调：

```python
TraceSink = Callable[[KnowledgeTrace], Awaitable[None] | None]
```

### 2.3 记忆值（`memory/types.py`）

```python
class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    SUMMARY = "summary"
    NOTE = "note"

@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    content: str                      # 非空；importance 必须落在 [0, 1]
    kind: MemoryKind = MemoryKind.NOTE
    tags: tuple[str, ...] = ()        # 构造时去重
    importance: float = 0.5
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

@dataclass(frozen=True, slots=True)
class MemoryRecord:
    content: str
    kind: MemoryKind = MemoryKind.NOTE
    source_thread_id: str | None = None
    tags: tuple[str, ...] = ()
    importance: float = 0.5
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
    memory_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    usage_count: int = 0
    last_accessed_at: datetime | None = None

@dataclass(frozen=True, slots=True)
class MemoryMatch:
    record: MemoryRecord
    score: float

@dataclass(frozen=True, slots=True)
class MemoryTrace:
    operation: str       # "consolidate" | "retrieve"
    success: bool
    item_count: int = 0
    thread_id: str | None = None
```

区分 `MemoryCandidate` 与 `MemoryRecord`：候选是提取器的**产出**（无持久化身份），记录是 store 的**存续形态**（带 `memory_id`、时间戳、`usage_count`、`last_accessed_at`）。`MemoryRecord` 的时间戳全部使用带时区的 `datetime.now(UTC)`，与运行时事件的时间精度保持一致。

### 2.4 上下文集成（`context/fragments.py`）

外部知识与记忆最终都汇入统一的片段模型：

```python
class ContextKind(StrEnum):
    RUNTIME = "runtime"; DEVELOPER = "developer"; PROJECT = "project"
    PERSONA = "persona"; SKILL = "skill"; MEMORY = "memory"
    RAG = "rag"; SUMMARY = "summary"

class ContextPriority(IntEnum):
    RUNTIME = 10; DEVELOPER = 20; PROJECT = 40; PERSONA = 50
    SKILL = 60; SUMMARY = 70; MEMORY = 80; RAG = 90

@dataclass(frozen=True, slots=True)
class ContextFragment:
    kind: ContextKind
    content: str
    source: str
    role: MessageRole = MessageRole.USER
    priority: int | None = None            # None 时取 kind 的默认优先级
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
```

`ContextPriority` 中 **MEMORY=80、RAG=90 是优先级最低（权威性最低）的两类**。`ContextFragment.render()` 生成带标签的用户消息：

```
<context kind="rag" source="https://example.test/fresh">
标题
摘要
URL: https://example.test/fresh
</context>
```

`ContextAssembler`（`max_chars=100_000`）对片段按 `(effective_priority, 插入序号)` 升序排序、按 `(kind, source, content)` 去重、按总字符预算截断；`Thread._request` 的组装顺序为 `instructions(DEVELOPER) → context 片段 → 摘要 → 会话历史消息`。因此 RAG/MEMORY 片段总是作为**低权威、靠近用户消息的用户角色数据**进入模型，不会覆盖 system/developer 指令。

## 3. 生命周期（Lifecycle）

### 3.1 搜索/检索/视觉调用的一生

```
调用方（Agent 工具流水线 或 应用直接调用）
   │  await router.search("...") / router.retrieve(...) / router.vision(...)
   ▼
KnowledgeRouter            ── provider 未配置 → RuntimeError("... is not configured")
   │  参数校验：query 非空、top_n >= 1（否则 ValueError）
   ▼
Provider 适配器
   │  1) 校验 API key；缺 key → SearchError/VisionError("..._API_KEY is required")
   │  2) observer.observe(Event("<op>.started", {provider, operation_id}))
   │  3) 创建/复用 httpx.AsyncClient（owned 标记决定是否自行关闭）
   │  4) _post_with_retry：POST + 指数退避重试（见第 11 节）
   │  5) 解析响应 → 中性值（tuple 截断到 top_n）
   │  6) trace_sink(KnowledgeTrace(..., success=True, item_count=n))
   │  7) observer.observe(Event("<op>.completed", {..., duration_ms}))
   ▼
调用方拿到 SearchResponse / tuple[RAGDocument, ...] / VisionResult
```

失败路径：`<op>.failed` 事件携带 `error_class` 与 `duration_ms`，失败 `KnowledgeTrace`（`success=False`）照常发出，然后**原始异常被重新抛出**——适配器只观察、不吞错。

### 3.2 路由层到上下文的转换

```
router.rag_context(query, top_n)
   └─ retrieve(query) → 每个 RAGDocument 变为
        ContextFragment(ContextKind.RAG, doc.text,
                        source=doc.source or f"rag:{index}",
                        metadata={"score": doc.score, **doc.metadata})

router.search_context(query, top_n)
   └─ search(query) → 每个 SearchResult 变为
        ContextFragment(ContextKind.RAG,
                        f"{title}\n{snippet}\nURL: {url}",
                        source=url or f"search:{index}",
                        metadata={"provider": ..., "query": ...})
```

搜索与 RAG 统一标记为 `ContextKind.RAG`——"外部证据都是数据，不是指令"；视觉结果没有对应的上下文入口，因为它通常是**即时的一次性回答**，直接返回给模型即可，不值得入上下文。

### 3.3 工具包装的生命周期

`router.tools()` 是**惰性按需**构造：只有 `search_provider is not None` 才生成 `web_search`，以此类推。三个工具共用参数：

```python
@tool(name="web_search", namespace="knowledge", source="provider", supports_parallel=True)
async def web_search(query: str, top_n: int = 5) -> SearchResponse: ...

@tool(name="rag_retrieve", namespace="knowledge", source="provider", supports_parallel=True)
async def rag_retrieve(query: str, top_n: int = 3) -> tuple[RAGDocument, ...]: ...

@tool(name="vision_analyze", namespace="knowledge", source="provider", supports_parallel=True)
async def vision_analyze(image: str, prompt: str) -> VisionResult: ...
```

生成后作为普通 `Tool` 交给 `Agent(tools=...)` / `ToolRegistry`：得益于 `source="provider"` 与 `supports_parallel=True`，模型的并发工具调用、`ToolExecutor` 的参数校验（pydantic `extra="forbid"`）、审批、超时（默认 30s）、输出截断（默认 20_000 字符）全部免费获得，`knowledge:*` 这三个工具与本地工具走同一条执行管线。

### 3.4 记忆流水线的一生（consolidate 与 retrieve）

**写入侧 `consolidate(thread_id, messages)`：**

```
extractor.extract(messages)            # 只扫 USER 消息；默认只认 Remember:/Memory:
   └─ (MemoryCandidate, ...)           # 例如 ("The preferred drink is jasmine tea", FACT, ("explicit",), 0.8)
        │ 逐个 store.remember(candidate, source_thread_id=thread_id)
        ▼
SQLiteMemoryStore._remember
   ├─ _fingerprint(candidate)          # sha256(kind\0 + 规范化 content)
   ├─ 命中 fingerprint？→ UPDATE updated_at / importance=MAX / source_thread_id=COALESCE
   └─ 未命中        → INSERT 新记录
   ▼
trace_sink(MemoryTrace("consolidate", True, len(records), thread_id))
   └─ 返回 tuple[MemoryRecord, ...]    # 含被去重合并的既有记录
```

**读取侧 `retrieve_context(query, *, current_thread_id, limit)`：**

```
store.search(query, limit, exclude_thread_id=current_thread_id)
   ├─ SQL WHERE：source_thread_id IS NULL OR != current_thread_id（可选）
   ├─ kinds 过滤（可选）
   ├─ 打分：token 重叠数 + 短语命中(+2) + importance
   ├─ 排序：(-score, -importance, memory_id) 取前 limit
   └─ usage_count+1, last_accessed_at 更新（选中的记录）
   ▼
转为 ContextFragment(ContextKind.MEMORY, content,
                     source=f"memory:{memory_id}",
                     metadata={"score", "kind", "source_thread_id"})
   ▼
trace_sink(MemoryTrace("retrieve", True, len(fragments), current_thread_id))
```

`exclude_thread_id=current_thread_id` 是一个关键设计：**当前 Thread 的消息本身就是即时记忆**，检索时排除本 Thread，避免把"正在说的话"当作"过去的记忆"重复注入。

### 3.5 工作记忆的生命周期

`WorkingMemory` 完全同步、无锁（单线程内使用），`set` 时先 `pop` 再插入（刷新 LRU 位置），超出 `max_items`（默认 64）时 `popitem(last=False)` 逐出最旧项；`get` 命中即刷新到队尾。`context()` 在非空时把全部键值渲染成一个 `ContextKind.MEMORY` 片段（`source="working-memory"`，`metadata={"items": n}`），空时返回 `None`。

## 4. 关键接口/类（Key interfaces/classes）

所有签名均与 `src/super_harness/knowledge/`、`src/super_harness/memory/` 中的实现一一对应。

### 4.1 knowledge 包

```python
# providers.py
class ZhipuWebSearchProvider:
    def __init__(self, *, api_key: str | None = None,
                 endpoint: str = "https://open.bigmodel.cn/api/paas/v4/web_search",
                 timeout: float = 20.0, retries: int = 2,
                 client: httpx.AsyncClient | None = None,
                 trace_sink: TraceSink | None = None,
                 observer: EventObserver | None = None) -> None
    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse
    # 环境变量：ZHIPU_SEARCH_API_KEY
    # 请求：{"search_query", "search_engine": "search_std", "count": top_n}

class HTTPRAGProvider:
    def __init__(self, base_url: str | None = None, *, api_key: str | None = None,
                 retrieve_path: str = "/retrieve", timeout: float = 10.0, retries: int = 1,
                 client: httpx.AsyncClient | None = None,
                 trace_sink: TraceSink | None = None,
                 observer: EventObserver | None = None) -> None
    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]
    # 环境变量：RAG_BASE_URL、RAG_API_KEY；请求：{"query", "top_n"} → {"results": [...]}

class ZhipuVisionProvider:
    def __init__(self, *, api_key: str | None = None,
                 endpoint: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                 model: str = "glm-4v-flash", timeout: float = 30.0, retries: int = 1,
                 max_image_bytes: int = 10_000_000,
                 client: httpx.AsyncClient | None = None,
                 trace_sink: TraceSink | None = None,
                 observer: EventObserver | None = None) -> None
    async def analyze(self, image: str | Path, prompt: str) -> VisionResult
    async def _image_url(self, image: str | Path) -> str
    # 环境变量：ZHIPU_VISION_API_KEY；路径型 image 会经 _image_url 编码为 data URL

# routing.py
class KnowledgeRouter:
    def __init__(self, *, search: WebSearchProvider | None = None,
                 rag: RAGProvider | None = None,
                 vision: VisionProvider | None = None) -> None
    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse
    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]
    async def vision(self, image: str, prompt: str) -> VisionResult
    async def rag_context(self, query: str, *, top_n: int = 3) -> tuple[ContextFragment, ...]
    async def search_context(self, query: str, *, top_n: int = 5) -> tuple[ContextFragment, ...]
    def tools(self) -> tuple[Tool, ...]
```

### 4.2 memory 包

```python
# working.py
@dataclass(slots=True)
class WorkingMemory:
    max_items: int = 64
    def set(self, key: str, value: object) -> None        # LRU 插入 + 逐出最旧
    def get(self, key: str, default: object = None) -> object  # 命中刷新
    def delete(self, key: str) -> bool
    def clear(self) -> None
    def snapshot(self) -> Mapping[str, object]
    def context(self, *, source: str = "working-memory") -> ContextFragment | None

# store.py
class MemoryStore(Protocol):
    async def remember(self, candidate: MemoryCandidate, *,
                       source_thread_id: str | None = None) -> MemoryRecord: ...
    async def get(self, memory_id: str) -> MemoryRecord | None: ...
    async def search(self, query: str, *, limit: int = 5,
                     exclude_thread_id: str | None = None,
                     kinds: Sequence[MemoryKind] = ()) -> tuple[MemoryMatch, ...]: ...
    async def forget(self, memory_id: str) -> bool: ...
    async def close(self) -> None: ...

class SQLiteMemoryStore:
    schema_version = 1
    def __init__(self, path: str | Path) -> None
    # 所有公开方法均为 async，内部 asyncio.to_thread 委托 _ 前缀同步实现

# pipeline.py
class MemoryExtractor(Protocol):
    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]: ...

class HeuristicMemoryExtractor:
    _explicit = re.compile(r"(?im)^\s*(?:remember|memory)\s*:\s*(.+)$")
    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]
    # 只处理 USER 消息；产出 MemoryKind.FACT、tags=("explicit",)、importance=0.8

class MemoryManager:
    def __init__(self, store: MemoryStore, extractor: MemoryExtractor | None = None,
                 *, trace_sink: MemoryTraceSink | None = None) -> None
    async def consolidate(self, thread_id: str,
                          messages: Sequence[Message]) -> tuple[MemoryRecord, ...]
    async def retrieve_context(self, query: str, *, current_thread_id: str | None = None,
                               limit: int = 5) -> tuple[ContextFragment, ...]
```

## 5. 并发/取消（Concurrency/cancellation）

### 5.1 异步 I/O 的线程边界

- 所有 HTTP 调用走 `httpx.AsyncClient`，协程内无阻塞调用。本地图像读取（`ZhipuVisionProvider._image_url`）用 `asyncio.to_thread(path.read_bytes)` 放到线程池，避免阻塞事件循环。
- `SQLiteMemoryStore` 的每个公开 async 方法都通过 `asyncio.to_thread` 委托给 `_` 前缀同步方法；SQLite 连接以 `threading.RLock` 保护（`check_same_thread=False`——因为 `to_thread` 会换线程执行）。WAL 模式允许读并发。
- `_emit` / `_observe` 同时接受同步与异步回调：`isinstance(result, Awaitable)` 才 `await`，因此 `trace_sink=traces.append`（同步）与 async 回调可混用。

### 5.2 取消传播

取消在适配器内部**始终原样穿透**：

```python
except asyncio.CancelledError:
    raise
```

`_post_with_retry` 的重试循环、`client.post` 挂起、`asyncio.sleep` 退避都支持协程取消；任务被取消时 `httpx` 抛出的 `asyncio.CancelledError` 不经任何规范化直接上行，**不会**被包装成 `SearchError/RAGError/VisionError`。测试 `test_provider_errors_timeout_retry_and_cancellation` 用一个永不返回的 MockTransport 验证了这一点：`task.cancel()` 后 `await task` 抛出的是 `asyncio.CancelledError`，而非 provider 错误。这与框架级 `CancelledError`（`super_harness.exceptions`）的分工一致：取消是独立于"provider 失败"的终止状态。

### 5.3 客户端所有权

每个适配器接受可注入的 `client: httpx.AsyncClient | None`。注入时（`owned=False`）适配器**不关闭**客户端，便于应用共享连接池；自建时（`owned=True`）在 `finally` 中 `await client.aclose()`。`client` 不注入时，每次调用新建、用完即关——单次调用者在没有连接池的情况下也不会泄漏套接字。

## 6. 持久化（Persistence）

### 6.1 SQLite 文件与 schema 版本

`SQLiteMemoryStore(path)` 在构造时 `mkdir(parents=True, exist_ok=True)` 创建父目录，开启 `PRAGMA journal_mode=WAL`，然后建表。`memory_meta` 表记录 `schema_version`：

```sql
CREATE TABLE IF NOT EXISTS memory_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
```

**版本守卫**：若磁盘上的 `schema_version` 大于运行时支持的 `1`，构造即抛 `MemoryError("memory database schema is newer than this runtime")`——旧运行时绝不读写新格式的库（宁可拒绝打开，防止数据损坏）。

### 6.2 memories 表结构

```sql
CREATE TABLE IF NOT EXISTS memories (
    memory_id       TEXT PRIMARY KEY,          -- MemoryRecord.memory_id（uuid4 hex）
    fingerprint     TEXT NOT NULL UNIQUE,      -- 规范化内容指纹，去重键
    content         TEXT NOT NULL,
    kind            TEXT NOT NULL,             -- MemoryKind.value
    source_thread_id TEXT,
    tags_json       TEXT NOT NULL,             -- json.dumps(tags, ensure_ascii=False)
    importance      REAL NOT NULL,             -- [0, 1]
    metadata_json   TEXT NOT NULL,             -- json.dumps(dict(metadata), ensure_ascii=False)
    created_at      TEXT NOT NULL,             -- ISO-8601 UTC
    updated_at      TEXT NOT NULL,
    usage_count     INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT
);
```

### 6.3 归一化指纹与 upsert

```python
def _fingerprint(candidate: MemoryCandidate) -> str:
    normalized = " ".join(candidate.content.casefold().split())  # casefold + 折叠空白
    return hashlib.sha256(f"{candidate.kind.value}\0{normalized}".encode()).hexdigest()
```

指纹把**等价**内容（`"The preferred drink is jasmine tea"` 与 `"  The preferred drink is jasmine tea  "`）归一到同一条记录。`remember` 命中指纹时执行合并式更新：

```sql
UPDATE memories SET updated_at=?, importance=MAX(importance, ?),
       source_thread_id=COALESCE(source_thread_id, ?) WHERE fingerprint=?
```

新候选与存量记录**谁的重要度高取谁**、`source_thread_id` 只补不覆盖；未命中则 INSERT 新记录。测试 `test_sqlite_memory_cross_thread_dedupe_reopen_and_forget` 验证：两个 Thread 写入同一事实返回**同一个 `memory_id`**，metadata 保留首条写入的 `("profile",)` 标签。

### 6.4 检索打分（纯确定性）

`_search` 先按 `exclude_thread_id` / `kinds` 过滤，再对每条记录打分：

```
score = len(query_tokens ∩ content_tokens)      # token 重叠（大小写折叠）
      + (2 if query.casefold() in content.casefold() else 0)  # 整段短语命中
      + record.importance                         # 重要度偏置
```

只保留 `overlap or phrase` 非零的记录，按 `(-score, -importance, memory_id)` 排序取前 `limit`；对选中的记录批量执行 `usage_count+1` 与 `last_accessed_at` 写入。打分在 SQL 之外于 Python 中完成，**零外部依赖、跨重启可复现**，与 RAG fixture（`tests/services/rag_server`）的确定性 token 重叠排序同源。

## 7. 事件/可观测性（Events/observability）

### 7.1 knowledge 事件（`Event` + `EventObserver`）

每个远端操作发出三个事件，`operation_id`（`uuid4().hex`）把同一操作的三条事件关联起来：

| 事件类型 | payload 关键字段 |
|---|---|
| `search.started` / `rag.started` / `vision.started` | `provider`、`operation_id`；vision 另含 `model` |
| `search.completed` / `rag.completed` / `vision.completed` | `provider`、`operation_id`、`item_count`、`duration_ms` |
| `search.failed` / `rag.failed` / `vision.failed` | `provider`、`operation_id`、`duration_ms`、`error_class` |

- provider 归一化名：搜索/视觉为 `"zhipu"`，RAG 为 `"http-rag"`（固定值，不含 host）。
- `Event` 是不可变 dataclass；payload 经 `MappingProxyType` 只读。观察口 `EventObserver.observe(event) -> object` 兼容同步与 `await` 两种实现（`_observe` 用 `inspect.isawaitable` 区分）。
- **敏感信息纪律**：事件 payload 只有 provider/operation_id/item_count/duration_ms/error_class/model，**绝不含查询原文、API key、图像数据**；异常 `details` 同样只含 `endpoint`、`status_code`、`attempt`。

### 7.2 KnowledgeTrace 汇（sink）

`KnowledgeTrace` 是**同步友好的轻量可观测通道**，适合记日志、埋点或喂给指标；`trace_sink` 为 `None` 时 `_emit` 直接返回，零开销。失败分支也发 trace（`success=False`、`item_count=0`），保证"每次尝试都有痕迹"。测试断言 `[trace.operation for trace in traces] == ["search", "vision"]`、`["consolidate", "consolidate", "retrieve"]`，证明 trace 是操作级、有序、无丢失的。

### 7.3 记忆事件

`MemoryManager` 每次 `consolidate` / `retrieve_context` 通过 `MemoryTraceSink` 各发一条 `MemoryTrace`。它不依赖 `Event`/observer——记忆是应用自编排的组件，sink 回调足以满足可观测性，避免与运行时事件流耦合。

## 8. Codex 参考（Codex reference）

本子系统的设计依据与证据链记录在 `docs/research/codex/`：

- `docs/research/codex/search-rag-vision.md` — 搜索/检索/视觉的行为契约：外部文本只有数据权威、凭证与图像永不进 trace、取消不被规范化为 provider 失败、`top_n` 同时约束请求与结果数、本地图像异步读取 + 大小限制 + MIME 校验 + data URL 编码、响应形态先规范化再进运行时。
- `docs/research/codex/working-and-long-term-memory.md` — 记忆的行为契约：会话历史是即时记忆的真相源、长期记录 provider 中立且不存凭证、提取保守且可替换、consolidation 对规范化内容去重、跨 Thread 检索可排除当前源 Thread、检索结果以用户角色注入、SQLite schema 拒绝更新版本、检索确定且有界并记录 usage。
- 关联章节：`agent-runtime-thread-turn.md`（上下文组装与用户角色权威）、`durable-thread-context-compaction.md`（Thread 消息作为会话记忆与压缩）。

## 9. Python 原生重设计（Python-native redesign）

Codex 的原型把搜索耦合在 OpenAI hosted tool 类型、Responses API 会话历史、Codex turn 元数据与 OpenAI 能力目录里；记忆则依赖内部模型 prompt、state job lease、rollout JSONL 与 Codex home 目录布局。Python 原生的对应设计：

- **三个异步 Protocol 替代 OpenAI 工具类型**：`WebSearchProvider` / `RAGProvider` / `VisionProvider`，鸭子类型，应用可注入任意实现。
- **Zhipu 端点信息完全封装在适配器内部**（`ZhipuWebSearchProvider`、`ZhipuVisionProvider`），`KnowledgeRouter` 与运行时零 provider SDK 依赖；`HTTPRAGProvider` 把冻结的 `POST /retrieve` 契约实现为独立适配器，RAG 与模型 provider 完全无关。
- **不可变中性值（`SearchResult`/`SearchResponse`/`RAGDocument`/`VisionResult`）**：规范化发生在适配器内，进入运行时之后就是纯数据。
- **可替换的 `MemoryExtractor` / `MemoryStore` 协议**：内置 `HeuristicMemoryExtractor` 完全无 LLM、无凭证；应用可以换成模型背书的提取器而不动持久化与检索。
- **`KnowledgeTrace` / `MemoryTrace` 用同步或异步回调**：可观测性保持 vendor 中立，不绑定特定上报格式。
- 记忆用**单一可移植 SQLite 文件**替代 Codex 的 Markdown/git 工作区。

## 10. 有意差异（Intentional differences）

与 Codex 原型及常见框架的对照：

1. **增加一等公民的外部 RAG 协议与确定性 fixture**——Codex 没有对应的 RAG 能力；`HTTPRAGProvider` + `tests/services/rag_server`（真实 `ThreadingHTTPServer` 实现 `POST /retrieve`，token 重叠确定性排序、可选 bearer 认证、`/test/slow` `/test/error` `/test/malformed` `/test/empty` 四种故障模式）把行为钉死在测试里。
2. **搜索与 RAG 上下文统一为 `ContextKind.RAG`、用户角色注入**——外部证据一律"数据权威"，不进入 developer/system 指令；优先级 90 是全局最低，排序在片段末尾。
3. **内置记忆提取器只认显式 `Remember:` / `Memory:` 行**（`(?im)^\s*(?:remember|memory)\s*:\s*(.+)$`，仅 USER 消息）——避免"静默发明用户事实"；`tags=("explicit",)`、`importance=0.8` 标记其来源与相对权重。
4. **记忆检索打分无向量模型依赖**：token 重叠 + 短语命中 + importance，确定性、可复现、零依赖，换取跨重启稳定与可测试性。
5. **`WorkingMemory` 作为显式 API 提供**：Codex 的"工作记忆"主要是会话历史；本框架额外提供有界 LRU 键值存储，`context()` 可随时渲染成 `ContextKind.MEMORY` 片段。
6. **`MemoryRecord` 携带结构化元数据**（kind/tags/importance/usage_count/last_accessed_at），为未来排序策略（按热度、按时效）留好字段。
7. **视觉 provider 可收 HTTPS URL**（provider 支持时）；本地文件经异步读取、10MB 上限、魔数签名校验后编码为 `data:...;base64,...` URL。trace 中永远只有 `{"model": ...}`，没有图像体。

## 11. 失败模型（Failure model）

统一异常层级：`SuperHarnessError` → `ProviderError` → `SearchError` / `RAGError` / `VisionError`（`exceptions.py`）。

### 11.1 分类

| 场景 | 结果 |
|---|---|
| 空 query / `top_n < 1` / 空 prompt | `ValueError`（本地参数校验，不触发重试） |
| 未配置 provider（`router.search` 等） | `RuntimeError("web search provider is not configured")` |
| 缺 API key | `SearchError("ZHIPU_SEARCH_API_KEY is required")` / `VisionError("ZHIPU_VISION_API_KEY is required")`、`RAGError("RAG_BASE_URL is required")` |
| HTTP 4xx/5xx（非重试状态） | `error_type("external provider request failed", details={"endpoint", "status_code", "attempt"})` |
| 响应形状非法（非 JSON 对象、`results` 非列表、RAG 项无 `text`、vision 无 `choices`） | 对应类型错误，`details` 含端点信息 |
| 本地图像不可读 / 超 10MB / 魔数不匹配 | `VisionError`（路径、字节数等脱敏信息在 details） |
| 协程取消 | `asyncio.CancelledError` 原样上行，不包装 |

### 11.2 重试与退避

`_post_with_retry` 对两类故障重试，尝试次数 = `retries + 1`（各适配器默认：搜索 2、RAG/视觉 1）：

- 瞬时 HTTP 状态：`408, 429, 500, 502, 503, 504`
- 传输层错误：`httpx.TransportError`

重试间隔为指数退避 `asyncio.sleep(0.05 * (2 ** attempt))`（0.05s → 0.1s → 0.2s），短小且总量有界。`httpx.HTTPStatusError`（非瞬时状态码）**不重试**，直接转类型化错误并带上 `status_code`。测试验证：`retries=1` 时 500 响应恰好尝试 2 次后抛 `SearchError`。

### 11.3 超时与脱敏

- 超时由每个适配器的 `timeout` 参数控制（搜索 20s / RAG 10s / 视觉 30s），超时表现为 `httpx.TimeoutException`（`TransportError` 子类），重试预算内会重试，耗尽后转为类型化错误；`status_code` 为 `None`。
- **脱敏纪律**：错误消息只含描述性文本；`details` 只含 `endpoint`/`status_code`/`attempt`/`path`/`bytes`。测试 `test_rag_real_http_timeout_and_typed_error` 明确断言 `"rag-test-token" not in str(caught.value.details)`——token 永不出现在异常详情中。
- 框架级 `CancelledError`（`SuperHarnessError` 子类）是公共边界上的规范化取消；底层 `asyncio.CancelledError` 由适配器原样穿透（见第 5.2 节），两条路径互补。

## 12. 扩展点（Extension points）

1. **新搜索/RAG/视觉后端**：实现对应 `Protocol`（三个方法签名见第 2.2 节），传入 `KnowledgeRouter`。适配器的 HTTP 形态、端点、响应解析都留在适配器内，router 与运行时零改动。
2. **替代 `KnowledgeTrace` 汇**：任何 `Callable[[KnowledgeTrace], Awaitable[None] | None]` 都可作为 `trace_sink`——同步列表追加、异步日志、指标上报皆可。
3. **替代记忆提取器**：实现 `MemoryExtractor.extract(messages) -> tuple[MemoryCandidate, ...]`，传入 `MemoryManager(store, my_extractor)`。例如模型背书的提取器可产出 `MemoryKind.DECISION`/`SUMMARY` 候选；测试中的 `CustomExtractor` 展示了替换后返回 `MemoryKind.SUMMARY` 的路径。
4. **替代持久化**：实现 `MemoryStore` 协议（remember/get/search/forget/close）即可换成 Postgres、文件或内存实现；`MemoryManager` 的所有逻辑只依赖协议。注意 `search` 的排序语义（打分字段由 store 自行决定）保持确定性即可。
5. **接入运行时可观测性**：把 `observer=EventObserver` 传给任意适配器，`search/rag/vision.*` 事件即汇入统一的事件流（redaction、span 关联由 observability 层负责）。
6. **复用工具流水线**：`router.tools()` 的输出直接喂 `Agent(tools=...)`、`MultiAgentLimits` 或 `Workflow` 节点；`knowledge:*` 工具自动继承校验、审批、超时、并行执行与 tool result 关联。

## 13. 测试（Tests）

对应 `tests/test_knowledge.py` 与 `tests/test_memory.py`（另有 `tests/services/rag_server` fixture）：

### 13.1 知识（`tests/test_knowledge.py`）

- `test_search_and_vision_use_real_local_http`（integration）：真实本地 `ThreadingHTTPServer` 上的搜索与视觉请求；断言请求体形状（`count=1`、`messages[0].content[0].image_url.url` 以 `data:image/png;base64,` 开头）、结果规范化（`url` 来自 `link`）、trace 顺序、以及**请求负载中不出现 `local-` 测试 token**。
- `test_rag_fixture_normalization_context_tools_and_auth`（integration）：`HTTPRAGProvider` 真实 HTTP、确定性检索（`canary deployment`）、`rag_context` 产出 `ContextKind.RAG` 且 `role.value == "user"`、`router.tools()[0]` 可被 `Tool.invoke` 直接调用、最终 `Agent(EvidenceModel(), context=fragments)` 能基于片段作答、bearer 认证生效、trace 全为 `retrieve`。
- `test_simple_rag_response_and_typed_malformed_error`：MockTransport 验证字符串/富对象两种结果形态的规范化；`{"wrong": []}` 抛出 `RAGError("...results list")`。
- `test_provider_errors_timeout_retry_and_cancellation`：500 响应在 `retries=1` 下尝试 2 次后抛 `SearchError`；永不返回的 MockTransport 支持 `task.cancel()` 后抛 `asyncio.CancelledError`（取消不被规范化）；空 key 抛 `VisionError("...required")`。
- `test_rag_real_http_timeout_and_typed_error`（integration）：`/test/slow` 超时（`timeout=0.03, retries=0`）抛 `RAGError` 且 `status_code is None`、details 无 token；`/test/malformed` 抛形状错误；`/test/error` 抛带 `status_code == 500` 的 `RAGError`。

### 13.2 记忆（`tests/test_memory.py`）

- `test_working_memory_is_bounded_lru_and_renders_data_context`：`max_items=2` 下第三条 `set` 逐出最旧项；`get` 刷新；`snapshot()` 内容正确；`context()` 产出 `ContextKind.MEMORY`、`MessageRole.USER`；`delete` 返回布尔。
- `test_sqlite_memory_cross_thread_dedupe_reopen_and_forget`（integration）：不同 Thread 写入等价事实（含空白差异）得到**同一 `memory_id`**；关闭重开后数据仍在；`exclude_thread_id` 生效；`forget` 后 `get` 为 `None`。
- `test_extraction_consolidation_retrieval_and_agent_chain`（integration）：`"Remember: The preferred drink is jasmine tea"` 被提取为 FACT 并存储；普通瞬态文本被忽略（`ignored == ()`）；`retrieve_context` 产出 `source.startswith("memory:")`、`metadata["source_thread_id"] == "thread-a"` 的 MEMORY 片段；`Agent(ContextModel(), context=context)` 能答出 `jasmine tea`；trace 序列为 `[consolidate, consolidate, retrieve]`；`CustomExtractor` 替换后产出 `MemoryKind.SUMMARY`。
- `test_sqlite_memory_rejects_newer_schema`：预置 `schema_version=999` 的库在构造时抛 `MemoryError("...newer...")`。

## 14. 限制/未来工作（Limitations/future work）

1. **内置提取器只认显式语句**：模型没有显式 `Remember:`/`Memory:` 时不会自动沉淀长期记忆；需要"自动记忆"的应用必须替换为模型背书的 `MemoryExtractor`。当前 `HeuristicMemoryExtractor` 生成的候选固定为 `FACT`/`("explicit",)`/`0.8`，不支持从语气推断偏好或决策。
2. **检索不做语义向量检索**：token 重叠 + 短语命中 + importance 在高度改写/同义表达上召回有限；`SQLiteMemoryStore.search` 全表扫描 + Python 打分，记忆量大时存在性能天花板（可在 store 层引入 FTS5 或向量索引，协议无需变化）。
3. **记忆合并策略粗糙**：`remember` 只做 `importance=MAX` 与 `source_thread_id` 补全，不做内容拼接或摘要合并；同一指纹的多条变体事实不会融合成一条更完整的记录。
4. **无全局过期/回收策略**：`forget` 需显式调用；没有基于 `usage_count`/`last_accessed_at` 的自动清理或冷记忆归档。字段已就位，策略未实现。
5. **WorkingMemory 无跨线程/跨进程共享**：进程内、单线程语义；多 worker 或分布式场景需要外部键值存储替代（`context()` 产出的片段模型不变）。
6. **KnowledgeRouter 不做结果缓存**：相同 `query` 在多个模型步之间会重复打远端；超时/重试参数是构造期固定的，不支持每次调用覆盖。
7. **vision 结果不可注入上下文**：`VisionResult` 只作为工具返回值；把视觉描述作为 `ContextKind.RAG` 片段持久注入（供后续步骤引用）是显式的未来扩展。
8. **适配器为 Zhipu/HTTP 专用**：`Zhipu*` 的端点、字段映射与 GLM-4V 约定内嵌在类中；Servingly 通用搜索/视觉 SDK 适配需新写 Protocol 实现（契约定型，成本主要在解析）。
9. **schema 只前向只读**：`schema_version=1` 只防"新库给旧运行时"，尚无可用的迁移路径（`ALTER TABLE` 升级流程未实现）。
10. **并发写入粒度**：`SQLiteMemoryStore` 以进程内 `RLock` 串行化写入；多进程同时打开同一文件依赖 SQLite WAL 本身的文件锁，未做应用层乐观并发（如 last-write-wins 消歧需要 `updated_at` 比较，当前未实现）。