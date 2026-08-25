# Providers and External Services

This document freezes the default V1 providers used for **real integration/E2E testing**. It does not hard-code them into architecture.

## 1. Main text/reasoning model

Provider: **DeepSeek**  
Model ID: `deepseek-v4-flash`  
Base URL: `https://api.deepseek.com`

Why:
- available for mainland-China deployment;
- OpenAI-compatible API;
- tool calls;
- JSON output;
- streaming;
- large context;
- current Responses API support;
- explicitly optimized for agent/Codex-style usage.

Environment:

```env
DEEPSEEK_API_KEY=
```

Never put the value in source or docs.

Provider implementation requirements:
- Chat Completions adapter
- Responses API adapter where useful
- streaming
- tool calling
- reasoning/thinking controls
- timeout/retry
- token usage normalization
- structured exceptions
- capability reporting

## 2. Vision model

Provider: **Zhipu AI**
V1 requested model ID: `glm-4v-flash`

Environment:

```env
ZHIPU_VISION_API_KEY=
```

Notes:
- Vision provider must be independent from the main model provider.
- `glm-4v-flash` is a lightweight/free image understanding model and is appropriate for initial real E2E.
- Architecture must allow upgrading to newer Zhipu visual models (for example `glm-4.6v-flash`) without code changes outside config.
- Test local image/base64 and image URL paths if provider supports them.

## 3. Web search

Provider: **Zhipu Web Search API**

Endpoint reference:
`POST https://open.bigmodel.cn/api/paas/v4/web_search`

Environment:

```env
ZHIPU_SEARCH_API_KEY=
```

Normalized result should include where available:
- title
- snippet/content
- url/link
- publisher/media
- publish date
- provider metadata

Provider should expose:
- query
- count/top_k
- recency
- domain filter
- engine/provider options
- timeout/retry/cancel
- request ID

Do not expose provider-specific response objects directly to Agent core.

## 4. RAG service

RAG is **external**.

Environment example:

```env
RAG_BASE_URL=http://127.0.0.1:8765
RAG_API_KEY=
```

Core contract:

```python
await rag.retrieve(query="...", top_k=5)
```

Minimum accepted external result:

```json
["text one", "text two"]
```

Preferred richer result:

```json
{
  "results": [
    {
      "text": "...",
      "score": 0.92,
      "source": "kb/document/12",
      "metadata": {"page": 8}
    }
  ]
}
```

Super Harness normalizes all formats into an internal `RAGDocument`.

## 5. No embedding requirement in core

Embedding/vector indexing is the responsibility of the external retrieval service. Super Harness V1 therefore does not need an embedding provider to satisfy RAG.

A future embedding capability may be added as an optional provider, but it must not become a prerequisite for core RAG usage.

## 6. Provider fallback philosophy

Core routing may support fallback chains, for example:

```yaml
models:
  main:
    providers:
      - type: deepseek
        model: deepseek-v4-flash
      - type: openai_compatible
        base_url: ${BACKUP_BASE_URL}
        model: ${BACKUP_MODEL}
```

Fallback must be policy-driven and observable, never silently switch providers without trace metadata.

## 7. Secrets

The user previously supplied live keys during planning. Treat those as compromised and assume they will be rotated.

Only variable names belong in repository:
- `DEEPSEEK_API_KEY`
- `ZHIPU_VISION_API_KEY`
- `ZHIPU_SEARCH_API_KEY`
- optional `RAG_API_KEY`

No real value may appear in:
- code
- tests
- fixtures
- docs
- examples
- CI YAML
- trace snapshots
- screenshots
