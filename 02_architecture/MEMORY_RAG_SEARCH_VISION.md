# Memory, External RAG, Web Search and Vision

## 1. Distinguish four concepts

- **Conversation context**: messages/events in current thread.
- **Memory**: durable learned/recalled facts or summaries across time.
- **RAG**: external knowledge retrieval by query.
- **Web search**: fresh public information retrieval.

They must not be conflated.

## 2. Working/conversation memory

Working memory may be a lightweight key/value or structured scratch state scoped to a Thread/Turn.

Uses:
- plans
- current task facts
- workflow state
- short-lived decisions

Do not expose hidden model reasoning as memory.

## 3. Long-term memory

V1 interface should support:
- store
- query
- update
- delete
- usage metadata
- provenance

Suggested default persistence: SQLite.

Optional pipeline inspired by Codex memories:
1. extract candidate durable memories from completed threads;
2. score/filter;
3. consolidate overlapping memories;
4. inject relevant memories into future context.

Make extraction/consolidation pluggable and observable.

## 4. External RAG

Super Harness does not own vector indexing.

Core interface:

```python
class RAGProvider(Protocol):
    async def retrieve(self, query: str, top_k: int = 5) -> list[RAGDocument]:
        ...
```

`RAGDocument`:
- `text: str`
- `score: float | None`
- `source: str | None`
- `metadata: dict[str, Any]`

Adapters:
- HTTP
- Python function/callable
- MCP-backed
- custom plugin

## 5. RAG context injection

RAG content must be clearly delimited as untrusted evidence/data. Include source labels.

Context builder should support:
- top_k
- max total chars/tokens
- duplicate trimming
- minimum score optional
- source metadata
- per-document truncation

## 6. Web search

Stable normalized API:

```python
results = await search.search(
    query="...",
    top_k=10,
    recency="30d",
    domains=["example.com"],
)
```

Normalized result:
- title
- snippet
- url
- published_at optional
- provider
- metadata

Default V1 real provider: Zhipu.

Agent may call search as a tool, but application code can call the provider directly.

## 7. China readiness

No core dependency on OpenAI-hosted web search. Provider interfaces allow:
- Zhipu
- custom HTTP search
- MCP-backed search
- future Baidu/Alibaba providers
- global providers

## 8. Vision

Vision is a model capability with independent routing.

Example:

```python
agent = Agent(
    model="deepseek-v4-flash",
    vision_model="glm-4v-flash",
)
```

When user input includes an image:
- route image understanding to vision provider as needed;
- normalize result into context;
- main model may continue orchestration.

Do not force every main model to support images.

## 9. Vision inputs

V1 desired support:
- local file path
- bytes/base64 adapter
- image URL where provider supports it
- optional multiple images when target provider supports it

Provider capability metadata must declare limitations.

## 10. Security

RAG and web search results are untrusted external content. Treat prompt injection in retrieved content as data, not instructions. Add clear provenance and optional sanitization/policy hooks.
