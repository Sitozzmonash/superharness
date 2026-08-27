---
id: guide-part4-knowledge
title: Knowledge (Memory / RAG / Search / Vision)
sidebar_position: 4
description: Master the Super Harness knowledge stack — bounded working memory, cross-thread long-term memory, external RAG retrieval, web search and vision analysis, combined into your Agent via KnowledgeRouter.
---

# Knowledge (Memory / RAG / Search / Vision)

This page explains Super Harness's "knowledge" capabilities: how to let an Agent remember short-term state, remember long-term facts across threads, retrieve documents from an external RAG service, search the live web, analyze images, and how to use `KnowledgeRouter` to inject retrieval results into context or expose retrieval as model-visible Tools. Every capability is described in terms of "how to use it and what behavior you get", not internal design.

## What this is / When to use

Super Harness splits "knowledge" into four layers, distinguished by lifecycle and source:

| Capability | Representative type | Lifecycle | Typical use |
| --- | --- | --- | --- |
| Working memory | `WorkingMemory` | In-process, bounded (default 64 items), LRU eviction | Temporary preferences, goals, context snapshots for the current task |
| Long-term memory | `SQLiteMemoryStore` + `MemoryManager` | Persisted to SQLite, reusable across threads | Remember long-lived user preferences, facts, decisions across sessions |
| External RAG | `HTTPRAGProvider` | External service, on demand | Retrieve from an enterprise knowledge base, release policy, doc chunks |
| Web search | `ZhipuWebSearchProvider` | Live, on demand | Latest / external / beyond-model-knowledge information |
| Vision | `ZhipuVisionProvider` | On-demand single image analysis | Read local / URL / data-URI image content |

When to use which:

- **Remember a little transient state for one run** (e.g. "reply in Chinese", "goal is to ship Phase 5") → `WorkingMemory`.
- **Remember facts across threads and processes** (e.g. "user prefers jasmine tea", "release requires a canary") → `SQLiteMemoryStore` + `MemoryManager`.
- **Have an independent knowledge / document base** (e.g. release policy, auth rules) → external RAG service + `HTTPRAGProvider`.
- **Need latest or networked information** (e.g. "latest Python version") → `ZhipuWebSearchProvider`.
- **Need to understand image content** (e.g. "describe this image", "identify the buttons in this screenshot") → `ZhipuVisionProvider`.
- **Let the model decide when to call retrieval** → register `KnowledgeRouter.tools()` as model-visible Tools.
- **Inject retrieval results directly as context without model decision** → `KnowledgeRouter.search_context()` / `rag_context()`.

All search / RAG / memory fragments are attributed `ContextKind.RAG` or `ContextKind.MEMORY` in context and are treated as **user-role external data** that can never override developer or project instructions.

## Prerequisites

- Super Harness installed (`pip install -e .`).
- Most examples here use `DeepSeekProvider`; configure `DEEPSEEK_API_KEY` as needed.
- **Only configure the providers you actually use.** Search needs `ZHIPU_SEARCH_API_KEY`; vision needs `ZHIPU_VISION_API_KEY`; RAG needs `RAG_BASE_URL` (and optionally `RAG_API_KEY`). Do not instantiate providers you have not configured.
- Before running examples that need the network / an external service, make sure the service is reachable (the RAG service must be started yourself, see "Mock RAG service tutorial" below).
- The long-term memory examples create a `memory.sqlite3` database file in the current directory.

## Quick start

The minimal "memory + context injection" workflow — turn a working-memory entry into a context fragment and feed it to an Agent:

```python
from super_harness import Agent, DeepSeekProvider, WorkingMemory

memory = WorkingMemory()
memory.set("response_language", "Chinese")
fragment = memory.context()
agent = Agent(DeepSeekProvider(), context=(() if fragment is None else (fragment,)))
print(agent.run("Introduce this project briefly.").text)
```

With `RAG_BASE_URL` configured, the minimal RAG retrieval:

```python
import asyncio
from super_harness import HTTPRAGProvider, KnowledgeRouter

async def main() -> None:
    router = KnowledgeRouter(rag=HTTPRAGProvider())
    fragments = await router.rag_context("What is the release policy?", top_n=3)
    for fragment in fragments:
        print(fragment.render().content)

asyncio.run(main())
```

Pass `fragments` to `Agent(..., context=fragments)` to let the Agent see the retrieval results; or register `router.tools()` to let the model retrieve on demand.

## Configuration

Super Harness reads credentials from environment variables at request time and **never writes credentials to events or logs**. Every knowledge provider also accepts explicit constructor arguments that take precedence over environment variables.

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `ZHIPU_SEARCH_API_KEY` | Zhipu API key for web search | none (`search()` raises `SearchError` when missing) |
| `ZHIPU_VISION_API_KEY` | Zhipu API key for vision analysis | none (`analyze()` raises `VisionError` when missing) |
| `RAG_BASE_URL` | RAG service base URL, e.g. `http://127.0.0.1:8765` | empty (`retrieve()` raises `RAGError` when missing) |
| `RAG_API_KEY` | Optional Bearer token for the RAG service | none |

Example: the `RAG_BASE_URL` default is read by `HTTPRAGProvider` at construction:

```python
from super_harness import HTTPRAGProvider

provider = HTTPRAGProvider()  # base_url comes from RAG_BASE_URL
```

You can also override explicitly in the constructor (higher precedence than environment variables):

```python
provider = HTTPRAGProvider(
    "http://127.0.0.1:8765",
    api_key="rag-secret-token",
    retrieve_path="/retrieve",
    timeout=10.0,
    retries=1,
)
```

---

# Working Memory

`WorkingMemory` is an **in-process, bounded, thread-local** key-value store that keeps at most `max_items=64` entries by default and evicts with a least-recently-used (LRU) policy. It is ideal for transient state that only needs to live for one run / one Thread lifetime.

## Basic usage

```python
from super_harness import WorkingMemory

memory = WorkingMemory(max_items=3)
memory.set("goal", "ship Phase 5")
memory.set("branch", "main")
print(memory.snapshot())
print(memory.context())
```

## Working-memory API

- `WorkingMemory(max_items=64)` — construct; `max_items < 1` raises `ValueError`.
- `set(key, value)` — write; an empty key raises `ValueError`. When over the limit, the least-recently-used entry is evicted.
- `get(key, default=None)` — read and mark the entry as most-recently-used; returns `default` if absent.
- `delete(key)` — delete; returns `True`/`False` depending on whether it existed.
- `clear()` — clear everything.
- `snapshot()` — return all current key-value pairs (a plain `dict` copy).
- `context(*, source="working-memory")` — returns `None` when empty; otherwise renders all entries into one `ContextFragment(ContextKind.MEMORY, ...)` that can be passed to `Agent(context=...)`.

## Basic example

Save a run-scoped preference and inject the rendered fragment into an Agent:

```python
from super_harness import Agent, DeepSeekProvider, WorkingMemory

memory = WorkingMemory()
memory.set("response_language", "Chinese")
fragment = memory.context()
agent = Agent(DeepSeekProvider(), context=(() if fragment is None else (fragment,)))
print(agent.run("Introduce this project briefly.").text)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/21_working_memory_agent.py)

## Real-world example

Maintain "user preference + current branch + remaining budget" across a multi-turn conversation, refreshing MRU on `get` and letting over-limit eviction drop the oldest entry:

```python
from super_harness import WorkingMemory

memory = WorkingMemory(max_items=64)
memory.set("user_name", "Ada")
memory.set("branch", "feature/knowledge")
memory.set("budget_remaining", 1200)

name = memory.get("user_name")          # read and mark most-recently-used
memory.set("budget_remaining", 1100)    # update, refresh MRU position
print(memory.snapshot())
print(memory.context())
```

## Advanced example (LRU eviction behaviour)

Verify bounded eviction: with `max_items=2`, inserting a third entry evicts the least-recently-used `second`, while `get("first")` already refreshed its MRU position so it survives:

```python
from super_harness import WorkingMemory

memory = WorkingMemory(max_items=2)
memory.set("first", 1)
memory.set("second", 2)
memory.get("first")     # refresh first's MRU position
memory.set("third", 3)  # evicts least-recently-used second
print(memory.snapshot())  # first and third remain
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/20_working_memory_lru.py)

---

# Long-term Memory

When memory must **persist across threads and processes**, use `SQLiteMemoryStore` as storage and `MemoryManager` as the pipeline (extract → consolidate → retrieve). `Thread.messages` remains the single-thread persistent conversation memory; long-term memory is specifically for reusable cross-thread facts.

## Basic usage

```python
import asyncio
from super_harness import MemoryCandidate, SQLiteMemoryStore

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    await store.remember(MemoryCandidate("Release requires a canary"), source_thread_id="thread-a")
    print(await store.search("release canary"))
    await store.close()

asyncio.run(main())
```

## Key types and API

- `MemoryCandidate(content, kind=NOTE, tags=(), importance=0.5, metadata={})` — memory awaiting consolidation; content non-empty, `importance ∈ [0,1]`.
- `MemoryKind` — enum: `FACT` / `PREFERENCE` / `DECISION` / `SUMMARY` / `NOTE`.
- `MemoryRecord` — consolidated record with `memory_id`, `source_thread_id`, `created_at`, `updated_at`, `usage_count`, `last_accessed_at`.
- `SQLiteMemoryStore(path)` — durable store:
  - `remember(candidate, *, source_thread_id=None)` — consolidate; content-fingerprint dedupe, re-writes merge and raise importance.
  - `get(memory_id)` / `forget(memory_id)` — read / delete.
  - `search(query, *, limit=5, exclude_thread_id=None, kinds=())` — keyword + phrase-overlap scored retrieval; hits increment `usage_count` and refresh `last_accessed_at`.
  - `close()` — close the connection.
- `MemoryManager(store, extractor=None, *, trace_sink=None)`:
  - `consolidate(thread_id, messages)` — extract candidates from messages via the extractor and consolidate them, returning a tuple of `MemoryRecord`.
  - `retrieve_context(query, *, current_thread_id=None, limit=5)` — retrieve and render into a tuple of `ContextFragment` for injection into an Agent.
- `MemoryExtractor` — protocol: `async def extract(messages) -> tuple[MemoryCandidate, ...]`.

## Configuration / environment variables

Long-term memory has no dedicated environment variables; the database path is given at `SQLiteMemoryStore(path)` construction. The default extractor does **not touch any credentials** and only matches explicit memory statements.

### Default extractor (HeuristicMemoryExtractor)

The default extractor **only accepts explicit lines starting with `Remember:` or `Memory:`** (case-insensitive, leading whitespace allowed). For example the user message `Remember: use jasmine tea` is extracted as a `FACT` candidate (importance 0.8, tags `("explicit",)`).

```python
from super_harness.memory.pipeline import HeuristicMemoryExtractor

extractor = HeuristicMemoryExtractor()
```

For application-specific or model-based extraction, provide a custom `MemoryExtractor` (implement the `extract(messages)` protocol).

## Basic example

Consolidate a fact and retrieve it:

```python
import asyncio
from super_harness import MemoryCandidate, SQLiteMemoryStore

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    await store.remember(MemoryCandidate("Release requires a canary"), source_thread_id="thread-a")
    print(await store.search("release canary"))
    await store.close()

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/22_long_term_memory.py)

## Real-world example (cross-thread reuse)

Consolidate memory from Thread A, then retrieve it in Thread B and inject it as context. `current_thread_id` makes retrieval **exclude the current thread's own memory**, so you reuse what "other threads remembered":

```python
import asyncio
from super_harness import MemoryManager, SQLiteMemoryStore

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store)
    fragments = await manager.retrieve_context("preferred editor", current_thread_id="thread-b")
    for fragment in fragments:
        print(fragment.source, fragment.content)
    await store.close()

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/23_cross_thread_memory.py)

## Advanced example (extract → consolidate → retrieve chain)

Hand a message containing an explicit memory statement to `consolidate`, which auto-extracts and consolidates it, then retrieves it back:

```python
import asyncio
from super_harness import MemoryManager, SQLiteMemoryStore
from super_harness.models import Message, MessageRole

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store)
    records = await manager.consolidate(
        "thread-a", [Message(MessageRole.USER, "Remember: use jasmine tea")]
    )
    print(records)
    await store.close()

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/24_memory_extraction.py)

### Custom extractor

```python
import asyncio
from super_harness import MemoryCandidate, MemoryKind, MemoryManager, SQLiteMemoryStore
from super_harness.memory.pipeline import MemoryExtractor
from super_harness.models import Message

class MyExtractor(MemoryExtractor):
    async def extract(self, messages):
        out = []
        for message in messages:
            if "CONSOLIDATE:" in message.content:
                for line in message.content.splitlines():
                    if line.startswith("CONSOLIDATE:"):
                        out.append(MemoryCandidate(line.split(":", 1)[1].strip(), MemoryKind.SUMMARY))
        return tuple(out)

async def main() -> None:
    store = SQLiteMemoryStore("memory.sqlite3")
    manager = MemoryManager(store, extractor=MyExtractor())
    records = await manager.consolidate("thread-a", [Message(1, "CONSOLIDATE: meet the deadline")])
    print(records)
    await store.close()

asyncio.run(main())
```

---

# External RAG

`HTTPRAGProvider` is an adapter for the **frozen `POST /retrieve` RAG contract**: it sends `{"query": ..., "top_n": ...}` to `RAG_BASE_URL/retrieve` and parses the returned `results` list into `RAGDocument`s. It is suitable for wiring an independent knowledge base into an Agent.

## Request / response contract

- Endpoint: `POST {RAG_BASE_URL}/retrieve`
- Request body: `{"query": "<search terms>", "top_n": <count>}`
- Optional auth: `Authorization: Bearer <RAG_API_KEY>`
- Response: a JSON object whose `results` is a list; each item may be a string, or an object `{"text": ..., "score": ..., "source": ..., "metadata": {...}}`.

## Basic usage

```python
import asyncio
from super_harness import HTTPRAGProvider

async def main() -> None:
    for document in await HTTPRAGProvider().retrieve("release policy", top_n=3):
        print(document.source, document.score, document.text)

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/13_rag_retrieve.py)

## Real-world example (context injection)

Use `KnowledgeRouter.rag_context` to render retrieved documents into context fragments for injection:

```python
import asyncio
from super_harness import KnowledgeRouter
from super_harness.knowledge import HTTPRAGProvider

async def main() -> None:
    router = KnowledgeRouter(rag=HTTPRAGProvider())
    for fragment in await router.rag_context("authentication rules"):
        print(fragment.render().content)

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/14_rag_context.py)

## Advanced example (register as a Tool)

Register RAG retrieval as a model-visible Tool so the model retrieves on demand:

```python
from super_harness import HTTPRAGProvider, KnowledgeRouter

router = KnowledgeRouter(rag=HTTPRAGProvider())
rag_tool = router.tools()[0]
print(rag_tool.qualified_name, rag_tool.description)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/15_rag_tool.py)

The generated Tool's `qualified_name` is `knowledge.rag_retrieve`, declaring the parameters `query`, `top_n`.

## Mock RAG service tutorial

The repo ships a **real runnable Mock RAG service**: the `RAGHandler` in `tests/services/rag_server/app.py` implements a `ThreadingHTTPServer` handler that provides **deterministic token-overlap retrieval** via `POST /retrieve`, with optional Bearer auth and several test endpoints.

It loads its corpus from the `corpus.json` file in the same directory (for example "The release policy requires a canary deployment before production." and two more entries).

### How to start it

`RAGHandler` has no `__main__` entry itself — run it with `ThreadingHTTPServer`. The following code starts it on `127.0.0.1:8765`:

```python
import threading
from http.server import ThreadingHTTPServer
from tests.services.rag_server import RAGHandler

RAGHandler.token = "rag-secret-token"   # optional: enable Bearer auth; set None to disable
server = ThreadingHTTPServer(("127.0.0.1", 8765), RAGHandler)
threading.Thread(target=server.serve_forever, daemon=True).start()
print("RAG mock listening on http://127.0.0.1:8765")
```

### Point a provider at it

Once running, point `HTTPRAGProvider` at the service:

```python
import asyncio
from super_harness import HTTPRAGProvider

async def main() -> None:
    provider = HTTPRAGProvider("http://127.0.0.1:8765", api_key="rag-secret-token")
    for document in await provider.retrieve("release policy", top_n=2):
        print(document.source, document.score, document.text)

asyncio.run(main())
```

### Test endpoints

`RAGHandler` supports several special paths to simulate failures and edge cases (`RAG_BASE_URL` refers to the base URL):

| Path | Behaviour |
| --- | --- |
| `/retrieve` | Normal retrieval, ranked by token overlap and capped at `top_n` |
| `/test/empty` | Returns `{"results": []}` (empty result) |
| `/test/slow` | Artificial 0.25s delay (timeout testing) |
| `/test/error` | Returns 500 (error-path testing) |
| `/test/malformed` | Returns 200 without `results` (malformed-response testing) |
| any other path | Returns 404 |

> Auth is enforced before any path handling: if `RAGHandler.token` is set, the request header must be `Authorization: Bearer <token>` or a 401 is returned.

---

# Web Search

`ZhipuWebSearchProvider` calls the Zhipu standalone web-search API (default `https://open.bigmodel.cn/api/paas/v4/web_search`) and returns a normalized `SearchResponse` with `title` / `url` / `snippet` / `published_at` fields.

## Basic usage

```python
import asyncio
from super_harness import ZhipuWebSearchProvider

async def main() -> None:
    response = await ZhipuWebSearchProvider().search("Python async context manager", top_n=3)
    for item in response.results:
        print(item.title, item.url)

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/10_search_basic.py)

## Real-world example (context injection)

Use `KnowledgeRouter.search_context` to render search results into context fragments with source URLs:

```python
import asyncio
from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

async def main() -> None:
    router = KnowledgeRouter(search=ZhipuWebSearchProvider())
    for fragment in await router.search_context("latest Python release", top_n=2):
        print(fragment.source, fragment.content)

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/11_search_context.py)

## Advanced example (register as a Tool)

```python
from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

router = KnowledgeRouter(search=ZhipuWebSearchProvider())
for item in router.tools():
    print(item.qualified_name, item.provider_definition().parameters)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/12_search_tool.py)

The generated Tool's `qualified_name` is `knowledge.web_search`.

---

# Vision

`ZhipuVisionProvider` is based on GLM-4V (default model `glm-4v-flash`). `analyze(image, prompt)` accepts three image inputs: **local file paths**, **HTTPS/HTTP URLs**, and **data URIs**. Local files are validated as real images (PNG/JPEG/GIF/WebP magic numbers) and sent as a Base64 data URI.

## Basic usage

Local image:

```python
import asyncio
from pathlib import Path
from super_harness import ZhipuVisionProvider

async def main() -> None:
    result = await ZhipuVisionProvider().analyze(Path("image.png"), "Describe this image")
    print(result.text)

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/16_vision_local.py)

## Real-world example (URL image)

```python
import asyncio
from super_harness import ZhipuVisionProvider

async def main() -> None:
    result = await ZhipuVisionProvider().analyze(
        "https://example.com/image.png", "List visible objects"
    )
    print(result.text)

asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/17_vision_url.py)

## Advanced example (register as a Tool)

```python
from super_harness import KnowledgeRouter, ZhipuVisionProvider

router = KnowledgeRouter(vision=ZhipuVisionProvider())
vision_tool = router.tools()[0]
print(vision_tool.qualified_name, vision_tool.provider_definition().parameters)
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/18_vision_tool.py)

The generated Tool's `qualified_name` is `knowledge.vision_analyze`, declaring the parameters `image`, `prompt`.

---

# KnowledgeRouter (combination routing)

`KnowledgeRouter` aggregates all knowledge providers behind one facade with two usage shapes: **context injection** (`search_context` / `rag_context`, returning `ContextFragment`) and **Tool exposure** (`tools()`, returning model-visible Tools). You can configure `search`, `rag`, `vision` in any combination; calling a method for an unconfigured provider raises `RuntimeError`.

## Basic usage (context injection)

```python
import asyncio
from super_harness import KnowledgeRouter, ZhipuWebSearchProvider

async def main() -> None:
    router = KnowledgeRouter(search=ZhipuWebSearchProvider())
    for fragment in await router.search_context("latest Python release", top_n=2):
        print(fragment.source, fragment.content)

asyncio.run(main())
```

## Method reference

- `search(query, *, top_n=5)` → `SearchResponse` (raises `RuntimeError` if search is not configured).
- `retrieve(query, *, top_n=3)` → `tuple[RAGDocument, ...]` (raises `RuntimeError` if RAG is not configured).
- `vision(image, prompt)` → `VisionResult` (raises `RuntimeError` if vision is not configured).
- `search_context(query, *, top_n=5)` → `tuple[ContextFragment, ...]`, source is the result URL, kind `RAG`.
- `rag_context(query, *, top_n=3)` → `tuple[ContextFragment, ...]`, source is the document source, kind `RAG`.
- `tools()` → `tuple[Tool, ...]`, generated per configured provider: `knowledge.web_search`, `knowledge.rag_retrieve`, `knowledge.vision_analyze` (all `supports_parallel=True`).

## Real-world example (configure all and inject into an Agent)

Configure search + RAG, inject both fragment sets into Agent context so the model answers from "latest web evidence + enterprise knowledge base":

```python
import asyncio
from super_harness import Agent, DeepSeekProvider, HTTPRAGProvider, KnowledgeRouter, ZhipuWebSearchProvider

async def main() -> None:
    router = KnowledgeRouter(
        search=ZhipuWebSearchProvider(),
        rag=HTTPRAGProvider(),
    )
    web_fragments = await router.search_context("Super Harness release notes", top_n=2)
    rag_fragments = await router.rag_context("release policy", top_n=2)
    fragments = web_fragments + rag_fragments
    agent = Agent(DeepSeekProvider(), context=fragments)
    print(agent.run("Summarize what we know about releases.").text)

asyncio.run(main())
```

## Advanced example (expose every capability as a Tool)

Expose search, RAG and vision at once as model-visible Tools for the `Agent`:

```python
from super_harness import Agent, DeepSeekProvider, HTTPRAGProvider, KnowledgeRouter, ZhipuVisionProvider, ZhipuWebSearchProvider

router = KnowledgeRouter(
    search=ZhipuWebSearchProvider(),
    rag=HTTPRAGProvider(),
    vision=ZhipuVisionProvider(),
)
agent = Agent(DeepSeekProvider(), tools=router.tools())
print(agent.run("Look up the current Python version, check the release policy, and read image.png.").text)
```

---

# API reference

```python
# Working memory
memory = WorkingMemory(max_items=64)
memory.set("key", value); memory.get("key", default); memory.delete("key"); memory.clear()
fragment = memory.context()              # ContextFragment | None
mapping = memory.snapshot()              # dict

# Long-term memory
store = SQLiteMemoryStore("memory.sqlite3")
record = await store.remember(MemoryCandidate("...", kind=MemoryKind.FACT), source_thread_id="t")
matches = await store.search("query", limit=5, exclude_thread_id="t", kinds=(MemoryKind.FACT,))
await store.close()
manager = MemoryManager(store, extractor=None, trace_sink=traces.append)
records = await manager.consolidate(thread_id, messages)
fragments = await manager.retrieve_context("query", current_thread_id="t", limit=5)

# External RAG
provider = HTTPRAGProvider(base_url, api_key=None, retrieve_path="/retrieve", timeout=10.0, retries=1)
documents = await provider.retrieve("query", top_n=3)   # tuple[RAGDocument, ...]

# Web search
search = ZhipuWebSearchProvider(api_key=None, timeout=20.0, retries=2)
response = await search.search("query", top_n=3)        # SearchResponse(results=[SearchResult])

# Vision
vision = ZhipuVisionProvider(api_key=None, model="glm-4v-flash", timeout=30.0, retries=1)
result = await vision.analyze(Path("image.png") | "https://...", "prompt")  # VisionResult

# Combination routing
router = KnowledgeRouter(search=..., rag=..., vision=...)
fragments = await router.search_context("q", top_n=5)   # tuple[ContextFragment, ...]
fragments = await router.rag_context("q", top_n=3)      # tuple[ContextFragment, ...]
tools = router.tools()                                  # tuple[Tool, ...]
```

# Events

Each provider emits the following events when an `observer` is configured (no content, payload carries metadata only):

| Event | Provider | Key payload fields |
| --- | --- | --- |
| `search.started` / `search.completed` / `search.failed` | Search | `provider`, `operation_id`, `item_count`, `duration_ms`, `error_class` |
| `rag.started` / `rag.completed` / `rag.failed` | RAG | `provider`, `operation_id`, `item_count`, `duration_ms`, `error_class` |
| `vision.started` / `vision.completed` / `vision.failed` | Vision | `provider`, `model`, `operation_id`, `item_count`, `duration_ms`, `error_class` |

Tracing (`trace_sink`): each provider also accepts `trace_sink: Callable[[KnowledgeTrace], ...]`, receiving `KnowledgeTrace(operation, provider, success, item_count, metadata)`. `MemoryManager` accepts a `trace_sink` receiving `MemoryTrace(operation, success, item_count, thread_id)`.

Example — count RAG calls in a test:

```python
traces: list = []
provider = HTTPRAGProvider("http://127.0.0.1:8765", trace_sink=traces.append)
```

# Errors / Timeouts / Retries

| Scenario | Exception | Notes |
| --- | --- | --- |
| Missing search key | `SearchError` | `ZHIPU_SEARCH_API_KEY` not set |
| Missing vision key | `VisionError` | `ZHIPU_VISION_API_KEY` not set |
| Missing RAG URL | `RAGError` | `RAG_BASE_URL` not set |
| Empty query / non-positive top_n | `ValueError` | `search` / `retrieve` / `analyze` input validation |
| Invalid / oversized local image | `VisionError` | unreadable, over `max_image_bytes` (default 10 MB), unrecognized format |
| Transport / HTTP 5xx / 429 | corresponding `*Error` | retryable; exponential backoff (`0.05 * 2**attempt`) |
| HTTP 4xx (except 429) | corresponding `*Error` | fails immediately, not retried |
| Malformed response | corresponding `*Error` | RAG missing `results`, invalid result item shape, etc. |
| Provider not configured | `RuntimeError` | calling `router.search` / `retrieve` / `vision` with the provider as `None` |

The retry budget is controlled by each provider's `retries` parameter (search default 2, RAG default 1, vision default 1). `HTTPRAGProvider` defaults to a 10s timeout, `ZhipuWebSearchProvider` 20s, `ZhipuVisionProvider` 30s. Caller cancellation (`asyncio.CancelledError`) always propagates.

# Combining with other features

- **Memory + durable Thread**: `SQLiteThreadStore`'s `Thread.messages` is single-thread persistent conversation memory; `SQLiteMemoryStore` adds cross-thread long-term facts. Use `thread.debug_context()` to inspect which RAG/memory fragments are injected and their sizes.
- **RAG / search + context injection**: pass the `ContextFragment`s returned by `search_context` / `rag_context` / `manager.retrieve_context` directly to `Agent(context=...)` for one-shot injection.
- **RAG / search / vision + Tools**: pass `router.tools()` to `Agent(tools=...)` and let the model call them on demand; `supports_parallel=True` allows several knowledge Tools to run concurrently in one step.
- **Compaction + memory**: `thread.compact()` compacts conversation history; long-term memory consolidation is independent of compaction and reusable across sessions.
- **Observability + knowledge**: configure an `observer` on knowledge providers to see `search.*` / `rag.*` / `vision.*` events in `Observability`.

# Security notes

- Credentials (`ZHIPU_SEARCH_API_KEY`, `ZHIPU_VISION_API_KEY`, `RAG_API_KEY`) are read from environment variables at request time and **never written to events, logs or traces**.
- Search / RAG / memory fragments are **user-role data** in context and cannot override developer or project instructions; `ContextKind.RAG` / `MEMORY` have lower priority than `DEVELOPER` / `PROJECT`.
- The default `HeuristicMemoryExtractor` deliberately does **not touch any credentials** and only matches explicit `Remember:` / `Memory:` lines, avoiding pulling sensitive information into long-term memory.
- Treat the external RAG service as untrusted input: retrieved document content is data, not instruction authority.
- Remote image URLs are sent directly to the vision provider; data URIs / local files are Base64-encoded before sending, so be mindful of the sensitivity of the analyzed content itself.
- In production, enable `RAG_API_KEY` (Bearer auth) and use HTTPS for the RAG service.

# Troubleshooting

| Symptom | Check |
| --- | --- |
| `SearchError: ZHIPU_SEARCH_API_KEY is required` | Search key not set; `export ZHIPU_SEARCH_API_KEY` or pass `api_key=` in the constructor |
| `VisionError: ZHIPU_VISION_API_KEY is required` | Vision key not set |
| `RAGError: RAG_BASE_URL is required` | `RAG_BASE_URL` not set; make sure the RAG service is running |
| Calling `router.search` raises `RuntimeError` | The matching provider was not passed when constructing `KnowledgeRouter` |
| RAG returns empty results | Check `/test/empty` or corpus mismatch; confirm a valid `top_n` |
| RAG timeout / 500 | Reproduce with `/test/slow`, `/test/error`; raise `timeout` or check the service |
| Malformed RAG response | Reproduce with `/test/malformed`; confirm the service returns a `results` list |
| RAG returns 401 | `RAGHandler.token` is set but no `api_key=` was passed, or the token does not match |
| Local image reports "not a recognized image" | Confirm the file is PNG/JPEG/GIF/WebP with correct magic numbers |
| Long-term memory returns nothing | The default extractor only recognizes the `Remember:` / `Memory:` prefix; make sure the message uses an explicit statement |
| `context()` returns `None` | Working memory is empty; `set` some key-values first |

# Links

- Runnable examples: `examples/10_search_basic.py` through `examples/24_memory_extraction.py` (see per-example links above).
- Related Internals: `src/super_harness/memory/` (working / types / store / pipeline) and `src/super_harness/knowledge/` (providers / routing / types).
- API reference: `HTTPRAGProvider`, `ZhipuWebSearchProvider`, `ZhipuVisionProvider`, `KnowledgeRouter`, `WorkingMemory`, `SQLiteMemoryStore`, `MemoryManager`, `MemoryCandidate`, `HeuristicMemoryExtractor`.
- Mock RAG service: `tests/services/rag_server/app.py` (handler) and `tests/services/rag_server/corpus.json` (corpus).
- Tests: `tests/test_knowledge.py`, `tests/test_memory.py`.
