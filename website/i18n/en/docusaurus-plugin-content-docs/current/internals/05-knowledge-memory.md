---
id: internals-05-knowledge-memory
title: "Chapter 5 — External Knowledge Pipeline & Memory"
sidebar_position: 5
description: How KnowledgeRouter, the WebSearch/RAG/Vision async protocols, and the memory pipeline (WorkingMemory, SQLiteMemoryStore, MemoryManager) work internally.
---

# Chapter 5 — External Knowledge Pipeline & Memory

This chapter explains how the `super_harness.knowledge` and `super_harness.memory` subsystems work internally: how external knowledge (web search, RAG retrieval, vision analysis) passes through unified async protocols, is normalized into immutable neutral values, injected into context, and exposed as model-visible tools; and how short-term memory (Thread messages, `WorkingMemory`) and long-term memory (`SQLiteMemoryStore`, `MemoryManager`) cooperate in layers. The relevant implementation lives in:

- `src/super_harness/knowledge/` — `types.py`, `providers.py`, `routing.py`
- `src/super_harness/memory/` — `types.py`, `working.py`, `store.py`, `pipeline.py`

This chapter answers "how it works and why it is designed this way"; configuration and usage are covered by the corresponding guide pages.

## 1. Responsibilities

### 1.1 The KnowledgeRouter boundary

`KnowledgeRouter` is the single facade between the runtime and the external knowledge world. It holds three optional async providers (`WebSearchProvider`, `RAGProvider`, `VisionProvider`) and has four responsibilities:

1. **Pass-through calls**: forwards `search` / `retrieve` / `vision` to the configured provider; raises a clear `RuntimeError` when a provider is not configured, rather than silently returning empty results.
2. **Context injection**: converts neutral results into `ContextKind.RAG`-tagged `ContextFragment`s (`rag_context` / `search_context`). These fragments render with user role (`MessageRole.USER`) — data authority only, never instruction authority.
3. **Tool exposure**: wraps each configured provider as an ordinary `Tool` under the `knowledge` namespace with `source="provider"` (`web_search`, `rag_retrieve`, `vision_analyze`), reusing the full tool validation/approval/timeout/result-normalization pipeline.
4. **Failure & observability boundary**: all remote failures are normalized into `SearchError` / `RAGError` / `VisionError` and emitted through `KnowledgeTrace` sinks and the `Event` observer, while credentials and image bodies never enter these channels.

`KnowledgeRouter` owns no provider lifecycle and no HTTP clients; it merely converges three protocols onto one Python object so applications can depend on a single facade.

### 1.2 Three layers of memory

Memory is split into three layers by recency and durability:

| Layer | Implementation | Lifetime | Responsibility |
|---|---|---|---|
| Session memory | `Thread.messages` | Persisted with the Thread | Full message history of the current session; immediate context |
| Working memory | `WorkingMemory` | In-process, bounded LRU | Application-level key/value state across model steps and tool calls |
| Long-term memory | `SQLiteMemoryStore` + `MemoryManager` | SQLite file, survives restarts | Normalized fact persistence and on-demand retrieval across Threads |

`MemoryManager` orchestrates the long-term memory pipeline: **replaceable extractor** → candidates (`MemoryCandidate`) → normalized upsert into the store → ranked retrieval → conversion into `ContextKind.MEMORY` fragments. The built-in `HeuristicMemoryExtractor` only recognizes explicit `Remember:` / `Memory:` lines and never invents user facts — a deliberate "extract conservatively, prefer omission" design.

## 2. Data model

### 2.1 Immutable neutral values in the knowledge layer (`knowledge/types.py`)

All values are `@dataclass(frozen=True, slots=True)`; `metadata` is frozen into a read-only mapping via `MappingProxyType(dict(...))` in `__post_init__`. Provider-specific response shapes are digested inside the adapters; the runtime only sees these neutral values:

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
    results: tuple[SearchResult, ...]   # already truncated to top_n
    provider: str                        # normalized provider name, e.g. "zhipu"

@dataclass(frozen=True, slots=True)
class RAGDocument:
    text: str                            # validated non-blank at construction, else ValueError
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

Key points:

- `SearchResponse.results` and the return value of `RAGProvider.retrieve` are **tuples** (immutable); `HTTPRAGProvider` returns `tuple[RAGDocument, ...]`.
- `KnowledgeTrace` is the only external observability payload: operation, provider, success flag, item count, and redacted metadata. It contains **no query text, no API keys, and no image bodies** (the `ZhipuVisionProvider` trace metadata only carries `{"model": ...}`).
- `RAGDocument` rejects empty text at construction, deflecting "malformed response" failures at the data layer.

### 2.2 Async provider protocols (`providers.py`)

The three `Protocol`s total three methods — the duck-typed contract every adapter must satisfy:

```python
class WebSearchProvider(Protocol):
    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse: ...

class RAGProvider(Protocol):
    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]: ...

class VisionProvider(Protocol):
    async def analyze(self, image: str | Path, prompt: str) -> VisionResult: ...
```

`TraceSink` deliberately supports both sync and async callbacks:

```python
TraceSink = Callable[[KnowledgeTrace], Awaitable[None] | None]
```

### 2.3 Memory values (`memory/types.py`)

```python
class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    SUMMARY = "summary"
    NOTE = "note"

@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    content: str                      # non-empty; importance must lie in [0, 1]
    kind: MemoryKind = MemoryKind.NOTE
    tags: tuple[str, ...] = ()        # deduplicated at construction
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

Note the distinction between `MemoryCandidate` and `MemoryRecord`: a candidate is the extractor's **output** (no durable identity); a record is the store's **persisted form** (with `memory_id`, timestamps, `usage_count`, `last_accessed_at`). All `MemoryRecord` timestamps use timezone-aware `datetime.now(UTC)`, matching the runtime's event timestamp convention.

### 2.4 Context integration (`context/fragments.py`)

Both external knowledge and memory converge on the shared fragment model:

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
    priority: int | None = None            # falls back to the kind default when None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
```

In `ContextPriority`, **MEMORY=80 and RAG=90 are the two lowest-authority kinds**. `ContextFragment.render()` produces a tagged user message:

```
<context kind="rag" source="https://example.test/fresh">
Title
Snippet
URL: https://example.test/fresh
</context>
```

`ContextAssembler` (`max_chars=100_000`) sorts fragments by `(effective_priority, insertion_index)` ascending, deduplicates by `(kind, source, content)`, and truncates to the total character budget; `Thread._request` assembles as `instructions(DEVELOPER) → context fragments → summaries → conversation history`. RAG/MEMORY fragments therefore always reach the model as **low-authority user-role data near the user message**, never overriding system/developer instructions.

## 3. Lifecycle

### 3.1 Life of a search/retrieve/vision call

```
Caller (Agent tool pipeline or direct application call)
   │  await router.search("...") / router.retrieve(...) / router.vision(...)
   ▼
KnowledgeRouter            ── provider missing → RuntimeError("... is not configured")
   │  argument validation: non-empty query, top_n >= 1 (else ValueError)
   ▼
Provider adapter
   │  1) API key check; missing → SearchError/VisionError("..._API_KEY is required")
   │  2) observer.observe(Event("<op>.started", {provider, operation_id}))
   │  3) create/reuse httpx.AsyncClient (owned flag decides whether to close it)
   │  4) _post_with_retry: POST + exponential backoff retry (see section 11)
   │  5) parse response → neutral values (tuple truncated to top_n)
   │  6) trace_sink(KnowledgeTrace(..., success=True, item_count=n))
   │  7) observer.observe(Event("<op>.completed", {..., duration_ms}))
   ▼
Caller receives SearchResponse / tuple[RAGDocument, ...] / VisionResult
```

On failure: a `<op>.failed` event carries `error_class` and `duration_ms`, a failed `KnowledgeTrace` (`success=False`) is still emitted, then **the original exception is re-raised** — adapters observe, never swallow.

### 3.2 Router-to-context conversion

```
router.rag_context(query, top_n)
   └─ retrieve(query) → each RAGDocument becomes
        ContextFragment(ContextKind.RAG, doc.text,
                        source=doc.source or f"rag:{index}",
                        metadata={"score": doc.score, **doc.metadata})

router.search_context(query, top_n)
   └─ search(query) → each SearchResult becomes
        ContextFragment(ContextKind.RAG,
                        f"{title}\n{snippet}\nURL: {url}",
                        source=url or f"search:{index}",
                        metadata={"provider": ..., "query": ...})
```

Search and RAG are uniformly tagged `ContextKind.RAG` — "external evidence is data, not instructions". Vision results have no context entry point because they are typically immediate one-shot answers returned straight to the model; they are not worth persisting into context.

### 3.3 Lifecycle of tool wrapping

`router.tools()` constructs **lazily per capability**: `web_search` exists only if `search_provider is not None`, and so on. All three share the same parameters:

```python
@tool(name="web_search", namespace="knowledge", source="provider", supports_parallel=True)
async def web_search(query: str, top_n: int = 5) -> SearchResponse: ...

@tool(name="rag_retrieve", namespace="knowledge", source="provider", supports_parallel=True)
async def rag_retrieve(query: str, top_n: int = 3) -> tuple[RAGDocument, ...]: ...

@tool(name="vision_analyze", namespace="knowledge", source="provider", supports_parallel=True)
async def vision_analyze(image: str, prompt: str) -> VisionResult: ...
```

Once produced, they are ordinary `Tool`s passed to `Agent(tools=...)` / `ToolRegistry`: thanks to `source="provider"` and `supports_parallel=True`, the model's parallel tool calls, `ToolExecutor` argument validation (pydantic `extra="forbid"`), approval, timeout (default 30s), output truncation (default 20,000 chars) all come for free — the `knowledge:*` tools run through the same execution pipeline as local tools.

### 3.4 Life of the memory pipeline (consolidate and retrieve)

**Write side `consolidate(thread_id, messages)`:**

```
extractor.extract(messages)            # USER messages only; default recognizes Remember:/Memory:
   └─ (MemoryCandidate, ...)           # e.g. ("The preferred drink is jasmine tea", FACT, ("explicit",), 0.8)
        │ one-by-one store.remember(candidate, source_thread_id=thread_id)
        ▼
SQLiteMemoryStore._remember
   ├─ _fingerprint(candidate)          # sha256(kind\0 + normalized content)
   ├─ fingerprint hit?  → UPDATE updated_at / importance=MAX / source_thread_id=COALESCE
   └─ no hit           → INSERT new record
   ▼
trace_sink(MemoryTrace("consolidate", True, len(records), thread_id))
   └─ returns tuple[MemoryRecord, ...]    # includes records merged by dedupe
```

**Read side `retrieve_context(query, *, current_thread_id, limit)`:**

```
store.search(query, limit, exclude_thread_id=current_thread_id)
   ├─ SQL WHERE: source_thread_id IS NULL OR != current_thread_id (optional)
   ├─ kinds filter (optional)
   ├─ scoring: token overlap + phrase hit (+2) + importance
   ├─ sort: (-score, -importance, memory_id), take first limit
   └─ usage_count+1, last_accessed_at updated for the selected records
   ▼
convert to ContextFragment(ContextKind.MEMORY, content,
                           source=f"memory:{memory_id}",
                           metadata={"score", "kind", "source_thread_id"})
   ▼
trace_sink(MemoryTrace("retrieve", True, len(fragments), current_thread_id))
```

`exclude_thread_id=current_thread_id` is a key design decision: **the current Thread's messages are themselves instant memory**, so retrieval excludes the source thread to avoid re-injecting "what is being said right now" as "memories of the past".

### 3.5 Life of working memory

`WorkingMemory` is fully synchronous and lock-free (intended for single-thread use). `set` first `pop`s then inserts (refreshing the LRU position); when the item count exceeds `max_items` (default 64), `popitem(last=False)` evicts the oldest entry. `get` refreshes the hit to the tail. `context()` renders all key/value pairs into a single `ContextKind.MEMORY` fragment (`source="working-memory"`, `metadata={"items": n}`) when non-empty, and returns `None` when empty.

## 4. Key interfaces/classes

Every signature matches the implementation in `src/super_harness/knowledge/` and `src/super_harness/memory/`.

### 4.1 knowledge package

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
    # Env: ZHIPU_SEARCH_API_KEY
    # Request: {"search_query", "search_engine": "search_std", "count": top_n}

class HTTPRAGProvider:
    def __init__(self, base_url: str | None = None, *, api_key: str | None = None,
                 retrieve_path: str = "/retrieve", timeout: float = 10.0, retries: int = 1,
                 client: httpx.AsyncClient | None = None,
                 trace_sink: TraceSink | None = None,
                 observer: EventObserver | None = None) -> None
    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]
    # Env: RAG_BASE_URL, RAG_API_KEY; request: {"query", "top_n"} → {"results": [...]}

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
    # Env: ZHIPU_VISION_API_KEY; path-type images are encoded to data URLs via _image_url

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

### 4.2 memory package

```python
# working.py
@dataclass(slots=True)
class WorkingMemory:
    max_items: int = 64
    def set(self, key: str, value: object) -> None        # LRU insert + evict oldest
    def get(self, key: str, default: object = None) -> object  # refresh on hit
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
    # All public methods are async, delegating to private sync "_"-prefixed impls via
    # asyncio.to_thread

# pipeline.py
class MemoryExtractor(Protocol):
    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]: ...

class HeuristicMemoryExtractor:
    _explicit = re.compile(r"(?im)^\s*(?:remember|memory)\s*:\s*(.+)$")
    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]
    # USER messages only; produces MemoryKind.FACT, tags=("explicit",), importance=0.8

class MemoryManager:
    def __init__(self, store: MemoryStore, extractor: MemoryExtractor | None = None,
                 *, trace_sink: MemoryTraceSink | None = None) -> None
    async def consolidate(self, thread_id: str,
                          messages: Sequence[Message]) -> tuple[MemoryRecord, ...]
    async def retrieve_context(self, query: str, *, current_thread_id: str | None = None,
                               limit: int = 5) -> tuple[ContextFragment, ...]
```

## 5. Concurrency/cancellation

### 5.1 Thread boundaries of async I/O

- All HTTP calls go through `httpx.AsyncClient` — no blocking calls inside coroutines. Local image reads (`ZhipuVisionProvider._image_url`) use `asyncio.to_thread(path.read_bytes)` to stay off the event loop.
- Every public async method of `SQLiteMemoryStore` delegates to a private synchronous `_`-prefixed method via `asyncio.to_thread`; the SQLite connection is protected by a `threading.RLock` (`check_same_thread=False` — required because `to_thread` switches threads). WAL mode permits concurrent reads.
- `_emit` / `_observe` accept sync and async callbacks alike: only `isinstance(result, Awaitable)` is awaited, so `trace_sink=traces.append` (sync) and async callbacks can be mixed.

### 5.2 Cancellation propagation

Cancellation always passes through adapters untouched:

```python
except asyncio.CancelledError:
    raise
```

Coroutine cancellation is supported throughout the retry loop, a blocked `client.post`, and the `asyncio.sleep` backoff; when a task is cancelled, the `asyncio.CancelledError` raised by httpx propagates un-normalized and is **never** wrapped into `SearchError`/`RAGError`/`VisionError`. `test_provider_errors_timeout_retry_and_cancellation` verifies this with a MockTransport that never returns: after `task.cancel()`, `await task` raises `asyncio.CancelledError`, not a provider error. This matches the division of labor with the framework-level `CancelledError` (`super_harness.exceptions`): cancellation is a termination state distinct from "provider failure".

### 5.3 Client ownership

Each adapter accepts an injectable `client: httpx.AsyncClient | None`. When injected (`owned=False`), the adapter does **not** close the client, allowing applications to share a connection pool; when self-created (`owned=True`), `finally` calls `await client.aclose()`. When no client is injected, a fresh one is created per call and closed afterwards — one-shot callers do not leak sockets without a pool.

## 6. Persistence

### 6.1 SQLite file and schema versioning

`SQLiteMemoryStore(path)` creates parent directories (`mkdir(parents=True, exist_ok=True)`), enables `PRAGMA journal_mode=WAL`, then creates tables. `memory_meta` records `schema_version`:

```sql
CREATE TABLE IF NOT EXISTS memory_meta (
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
```

**Version guard**: if the on-disk `schema_version` exceeds the runtime-supported `1`, construction raises `MemoryError("memory database schema is newer than this runtime")` — an old runtime never reads a newer-format database (refusing to open is safer than risking corruption).

### 6.2 The memories table

```sql
CREATE TABLE IF NOT EXISTS memories (
    memory_id       TEXT PRIMARY KEY,          -- MemoryRecord.memory_id (uuid4 hex)
    fingerprint     TEXT NOT NULL UNIQUE,      -- normalized content fingerprint, dedupe key
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

### 6.3 Normalized fingerprint and upsert

```python
def _fingerprint(candidate: MemoryCandidate) -> str:
    normalized = " ".join(candidate.content.casefold().split())  # casefold + collapse whitespace
    return hashlib.sha256(f"{candidate.kind.value}\0{normalized}".encode()).hexdigest()
```

The fingerprint collapses **equivalent** content (e.g. `"The preferred drink is jasmine tea"` vs `"  The preferred drink is jasmine tea  "`) into one record. When `remember` hits the fingerprint, it performs a merge update:

```sql
UPDATE memories SET updated_at=?, importance=MAX(importance, ?),
       source_thread_id=COALESCE(source_thread_id, ?) WHERE fingerprint=?
```

The higher importance wins (`MAX(importance, ?)`), and `source_thread_id` is back-filled but never overwritten; a miss INSERTs a new record. `test_sqlite_memory_cross_thread_dedupe_reopen_and_forget` verifies that two Threads writing the same fact get back the **same `memory_id`**, with metadata preserved from the first write (`("profile",)` tags).

### 6.4 Deterministic retrieval scoring

`_search` filters by `exclude_thread_id` / `kinds` first, then scores every record:

```
score = len(query_tokens ∩ content_tokens)      # token overlap (casefolded)
      + (2 if query.casefold() in content.casefold() else 0)  # full-phrase hit
      + record.importance                         # importance bias
```

Only records with non-zero (`overlap or phrase`) survive; they are sorted by `(-score, -importance, memory_id)` and truncated to `limit`; the selected records get a batched `usage_count+1` and `last_accessed_at` write. Scoring happens in Python outside SQL — **zero external dependencies, reproducible across restarts** — the same spirit as the deterministic token-overlap ranking in the RAG fixture (`tests/services/rag_server`).

## 7. Events/observability

### 7.1 Knowledge events (`Event` + `EventObserver`)

Each remote operation emits three events; `operation_id` (`uuid4().hex`) correlates them:

| Event type | Key payload fields |
|---|---|
| `search.started` / `rag.started` / `vision.started` | `provider`, `operation_id`; vision also `model` |
| `search.completed` / `rag.completed` / `vision.completed` | `provider`, `operation_id`, `item_count`, `duration_ms` |
| `search.failed` / `rag.failed` / `vision.failed` | `provider`, `operation_id`, `duration_ms`, `error_class` |

- Normalized provider names: `"zhipu"` for search/vision, `"http-rag"` for RAG (fixed strings, no host).
- `Event` is an immutable dataclass; payloads are read-only via `MappingProxyType`. The `EventObserver.observe(event) -> object` observer supports both sync and `await`-able implementations (`_observe` distinguishes via `inspect.isawaitable`).
- **Secrets discipline**: event payloads contain only provider/operation_id/item_count/duration_ms/error_class/model — **never the query text, API keys, or image data**; exception `details` likewise only carry `endpoint`, `status_code`, `attempt`.

### 7.2 The KnowledgeTrace sink

`KnowledgeTrace` is a **sync-friendly lightweight observability channel** suited for logging, metrics, or instrumentation; when `trace_sink` is `None`, `_emit` returns immediately with zero overhead. Failure branches also emit traces (`success=False`, `item_count=0`), guaranteeing "every attempt leaves a trace". Tests assert `[trace.operation for trace in traces] == ["search", "vision"]` and `["consolidate", "consolidate", "retrieve"]`, proving traces are operation-level, ordered, and lossless.

### 7.3 Memory traces

`MemoryManager` emits one `MemoryTrace` per `consolidate` / `retrieve_context` through `MemoryTraceSink`. It does not depend on `Event`/observer — memory is an application-orchestrated component, and a sink callback is sufficient observability without coupling to the runtime event stream.

## 8. Codex reference

The design rationale and evidence chain for this subsystem live in `docs/research/codex/`:

- `docs/research/codex/search-rag-vision.md` — behavioral contract for search/retrieval/vision: external text has data authority only, credentials and images never enter traces, cancellation is not normalized into a provider failure, `top_n` bounds both request and normalized result counts, local images are read async / size-bounded / MIME-checked / encoded as data URLs, and response shapes are normalized before entering the runtime.
- `docs/research/codex/working-and-long-term-memory.md` — behavioral contract for memory: conversation history is the source of truth for instant memory, long-term records are provider-neutral and store no credentials, extraction is conservative and replaceable, consolidation deduplicates normalized content, cross-thread retrieval can exclude the current source thread, retrieved memory is user-role data not instruction authority, SQLite schema versions reject newer incompatible databases, and search is deterministic, bounded, records usage, and survives restart.
- Related chapters: `agent-runtime-thread-turn.md` (context assembly and user-role authority), `durable-thread-context-compaction.md` (Thread messages as session memory and compaction).

## 9. Python-native redesign

The Codex prototype couples search to OpenAI hosted tool types, Responses API conversation history, Codex turn metadata, and the OpenAI capability catalog; its memory depends on internal model prompts, state job leases, rollout JSONL, and the Codex home layout. The Python-native counterpart:

- **Three async Protocols replace OpenAI tool types**: `WebSearchProvider` / `RAGProvider` / `VisionProvider` — duck-typed, any implementation is injectable.
- **Zhipu endpoint details are fully encapsulated in the adapters** (`ZhipuWebSearchProvider`, `ZhipuVisionProvider`); `KnowledgeRouter` and the runtime have zero provider-SDK dependency. `HTTPRAGProvider` implements the frozen `POST /retrieve` contract as a standalone adapter, keeping RAG completely independent of the model provider.
- **Immutable neutral values (`SearchResult`/`SearchResponse`/`RAGDocument`/`VisionResult`)**: normalization happens inside adapters; after that, pure data flows through the runtime.
- **Replaceable `MemoryExtractor` / `MemoryStore` protocols**: the built-in `HeuristicMemoryExtractor` is entirely LLM-free and credential-free; applications may substitute a model-backed extractor without touching persistence or retrieval.
- **`KnowledgeTrace` / `MemoryTrace` use sync-or-async callbacks**, keeping observability vendor-neutral and unbound to any particular reporting format.
- Memory uses a **single portable SQLite file** instead of Codex's Markdown/git workspace.

## 10. Intentional differences

Compared with the Codex prototype and common frameworks:

1. **First-class external RAG protocol plus a deterministic fixture** — Codex has no RAG capability here; `HTTPRAGProvider` + `tests/services/rag_server` (a real `ThreadingHTTPServer` implementing `POST /retrieve` with deterministic token-overlap ranking, optional bearer auth, and four failure modes: `/test/slow`, `/test/error`, `/test/malformed`, `/test/empty`) pins the behavior down in tests.
2. **Search and RAG context are uniformly `ContextKind.RAG`, injected as user role** — external evidence is always "data authority", never entering developer/system instructions; priority 90 is globally lowest, sorting these fragments last.
3. **The built-in memory extractor only recognizes explicit `Remember:` / `Memory:` lines** (`(?im)^\s*(?:remember|memory)\s*:\s*(.+)$`, USER messages only) — avoiding "silently invented user facts"; produced candidates carry `tags=("explicit",)` and `importance=0.8`.
4. **Memory retrieval scoring has no vector-model dependency**: token overlap + phrase hit + importance — deterministic, reproducible, dependency-free, in exchange for cross-restart stability and testability.
5. **`WorkingMemory` is an explicit API**: Codex's "working memory" is mostly conversation history; this framework additionally provides a bounded LRU key/value store whose `context()` renders a `ContextKind.MEMORY` fragment on demand.
6. **`MemoryRecord` carries structured metadata** (kind/tags/importance/usage_count/last_accessed_at), leaving fields ready for future ranking strategies (by heat, by recency).
7. **Vision providers may receive HTTPS URLs** (when the provider supports them); local files are asynchronously read, capped at 10MB, magic-signature validated, and encoded as `data:...;base64,...` URLs. Traces always contain only `{"model": ...}` — never image bodies.

## 11. Failure model

Unified exception hierarchy: `SuperHarnessError` → `ProviderError` → `SearchError` / `RAGError` / `VisionError` (`exceptions.py`).

### 11.1 Classification

| Scenario | Result |
|---|---|
| Empty query / `top_n < 1` / empty prompt | `ValueError` (local argument validation, no retry) |
| Provider not configured (`router.search`, etc.) | `RuntimeError("web search provider is not configured")` |
| Missing API key | `SearchError("ZHIPU_SEARCH_API_KEY is required")` / `VisionError("ZHIPU_VISION_API_KEY is required")` / `RAGError("RAG_BASE_URL is required")` |
| HTTP 4xx/5xx (non-retryable status) | `error_type("external provider request failed", details={"endpoint", "status_code", "attempt"})` |
| Malformed response (non-JSON object, `results` not a list, RAG item without `text`, vision without `choices`) | corresponding typed error; `details` carry endpoint info |
| Local image unreadable / over 10MB / magic mismatch | `VisionError` (redacted info such as path/bytes in `details`) |
| Coroutine cancellation | `asyncio.CancelledError` propagates untouched, never wrapped |

### 11.2 Retry and backoff

`_post_with_retry` retries two failure classes, with `retries + 1` total attempts (adapter defaults: search 2, RAG/vision 1):

- Transient HTTP statuses: `408, 429, 500, 502, 503, 504`
- Transport errors: `httpx.TransportError`

Backoff is exponential — `asyncio.sleep(0.05 * (2 ** attempt))` (0.05s → 0.1s → 0.2s) — short and bounded overall. `httpx.HTTPStatusError` for non-transient status codes is **not** retried; it converts directly to a typed error carrying `status_code`. The tests verify that a 500 response with `retries=1` attempts exactly twice before raising `SearchError`.

### 11.3 Timeouts and redaction

- Timeouts are governed by each adapter's `timeout` parameter (search 20s / RAG 10s / vision 30s); a timeout surfaces as `httpx.TimeoutException` (a `TransportError` subclass), is retried within the budget, and becomes a typed error once exhausted, with `status_code` set to `None`.
- **Redaction discipline**: error messages contain descriptive text only; `details` only carry `endpoint`/`status_code`/`attempt`/`path`/`bytes`. `test_rag_real_http_timeout_and_typed_error` explicitly asserts `"rag-test-token" not in str(caught.value.details)` — tokens never appear in exception details.
- The framework-level `CancelledError` (a `SuperHarnessError` subclass) is the normalized cancellation at public boundaries; the low-level `asyncio.CancelledError` passes through adapters untouched (section 5.2). The two paths are complementary.

## 12. Extension points

1. **New search/RAG/vision backends**: implement the corresponding `Protocol` (three method signatures in section 2.2) and pass it to `KnowledgeRouter`. HTTP shapes, endpoints, and response parsing stay inside the adapter; the router and runtime change nothing.
2. **Alternative `KnowledgeTrace` sinks**: any `Callable[[KnowledgeTrace], Awaitable[None] | None]` works as `trace_sink` — sync list appends, async logging, or metrics reporting.
3. **Alternative memory extractors**: implement `MemoryExtractor.extract(messages) -> tuple[MemoryCandidate, ...]` and pass it to `MemoryManager(store, my_extractor)`. A model-backed extractor, for example, could produce `MemoryKind.DECISION`/`SUMMARY` candidates; the `CustomExtractor` in the tests demonstrates the replacement path yielding `MemoryKind.SUMMARY`.
4. **Alternative persistence**: implement the `MemoryStore` protocol (remember/get/search/forget/close) to swap in Postgres, files, or an in-memory implementation; `MemoryManager` depends only on the protocol. Note that keeping `search`'s ranking semantics (scoring is the store's business) deterministic suffices.
5. **Hook into runtime observability**: pass an `observer=EventObserver` to any adapter and `search/rag/vision.*` events merge into the unified event stream (redaction and span correlation handled by the observability layer).
6. **Reuse the tool pipeline**: feed `router.tools()` output straight into `Agent(tools=...)`, `MultiAgentLimits`, or `Workflow` nodes; the `knowledge:*` tools automatically inherit validation, approval, timeout, parallel execution, and tool-result correlation.

## 13. Tests

Covered by `tests/test_knowledge.py` and `tests/test_memory.py` (plus the `tests/services/rag_server` fixture):

### 13.1 Knowledge (`tests/test_knowledge.py`)

- `test_search_and_vision_use_real_local_http` (integration): search and vision over a real local `ThreadingHTTPServer`; asserts request shapes (`count=1`, `messages[0].content[0].image_url.url` starts with `data:image/png;base64,`), result normalization (`url` taken from `link`), trace order, and that **no `local-` test token appears in any request payload**.
- `test_rag_fixture_normalization_context_tools_and_auth` (integration): `HTTPRAGProvider` over real HTTP with deterministic retrieval (`canary deployment`); `rag_context` yields `ContextKind.RAG` fragments with `role.value == "user"`; `router.tools()[0]` is invocable via `Tool.invoke`; `Agent(EvidenceModel(), context=fragments)` answers from the fragments; bearer auth works; all traces are `retrieve`.
- `test_simple_rag_response_and_typed_malformed_error`: MockTransport verifies normalization of both plain-string and rich-object result shapes; `{"wrong": []}` raises `RAGError("...results list")`.
- `test_provider_errors_timeout_retry_and_cancellation`: a 500 response with `retries=1` attempts twice then raises `SearchError`; a never-returning MockTransport supports `task.cancel()` followed by `asyncio.CancelledError` (cancellation un-normalized); an empty key raises `VisionError("...required")`.
- `test_rag_real_http_timeout_and_typed_error` (integration): `/test/slow` times out (`timeout=0.03, retries=0`) raising `RAGError` with `status_code is None` and no token in details; `/test/malformed` raises a shape error; `/test/error` raises `RAGError` with `status_code == 500`.

### 13.2 Memory (`tests/test_memory.py`)

- `test_working_memory_is_bounded_lru_and_renders_data_context`: with `max_items=2`, a third `set` evicts the oldest entry; `get` refreshes; `snapshot()` is correct; `context()` yields `ContextKind.MEMORY` with `MessageRole.USER`; `delete` returns a boolean.
- `test_sqlite_memory_cross_thread_dedupe_reopen_and_forget` (integration): equivalent facts written from different Threads (including whitespace variants) get **the same `memory_id`**; data survives close/reopen; `exclude_thread_id` works; after `forget`, `get` returns `None`.
- `test_extraction_consolidation_retrieval_and_agent_chain` (integration): `"Remember: The preferred drink is jasmine tea"` is extracted as a FACT and stored; ordinary transient text is ignored (`ignored == ()`); `retrieve_context` yields MEMORY fragments with `source.startswith("memory:")` and `metadata["source_thread_id"] == "thread-a"`; an `Agent(ContextModel(), context=context)` answers `jasmine tea`; the trace sequence is `[consolidate, consolidate, retrieve]`; replacing the extractor with `CustomExtractor` yields `MemoryKind.SUMMARY`.
- `test_sqlite_memory_rejects_newer_schema`: a database pre-seeded with `schema_version=999` raises `MemoryError("...newer...")` at construction.

## 14. Limitations/future work

1. **The built-in extractor only recognizes explicit statements**: without an explicit `Remember:`/`Memory:` line, no long-term memory is deposited; applications needing "automatic memory" must swap in a model-backed `MemoryExtractor`. `HeuristicMemoryExtractor` currently fixes candidates to `FACT`/`("explicit",)`/`0.8` and cannot infer preferences or decisions from phrasing.
2. **Retrieval is not semantic vector search**: token overlap + phrase hit + importance has limited recall on heavily paraphrased or synonymous expressions; `SQLiteMemoryStore.search` scans the full table and scores in Python, so there is a performance ceiling at scale (FTS5 or a vector index could be added at the store layer without protocol changes).
3. **Merging is coarse**: `remember` only does `importance=MAX` and `source_thread_id` back-fill — no content concatenation or summary merging; variant facts under one fingerprint never fuse into a richer record.
4. **No global expiry/reclamation**: `forget` must be called explicitly; there is no automatic cleanup or cold-memory archiving based on `usage_count`/`last_accessed_at`. The fields are in place; the policy is not.
5. **WorkingMemory is not shared across threads/processes**: in-process, single-thread semantics; multi-worker or distributed scenarios need an external key/value store instead (the `context()` fragment model stays unchanged).
6. **KnowledgeRouter does not cache results**: the same `query` re-hits the remote across model steps; timeout/retry parameters are fixed at construction and not overridable per call.
7. **Vision results cannot be injected into context**: `VisionResult` is only a tool return value; persisting a vision description as a `ContextKind.RAG` fragment for later steps is an explicit future extension.
8. **Adapters are Zhipu/HTTP specific**: the `Zhipu*` endpoints, field mappings, and GLM-4V conventions are embedded in the classes; generic search/vision SDK adapters require new `Protocol` implementations (the contract is fixed; the cost is mostly parsing).
9. **Schema is forward-read-only**: `schema_version=1` only guards "newer database against older runtime"; no migration path (`ALTER TABLE` upgrade flow) is implemented yet.
10. **Write granularity**: `SQLiteMemoryStore` serializes writes with an in-process `RLock`; multi-process access to the same file relies on SQLite WAL's own file locking, and application-level optimistic concurrency (e.g. last-write-wins disambiguation via `updated_at` comparison) is not implemented.