---
id: guide-part2-models
title: "User Guide Part II: Models & Inputs"
sidebar_position: 2
description: Configure the main text model (DeepSeek), custom OpenAI-compatible providers, vision models, capability fallback, and structured output, plus streaming, errors, and security.
---

# User Guide Part II: Models & Inputs

This page explains how to configure and use **model providers** for your Agent, and how to feed **inputs** (text, images, structured-output constraints) to the model correctly. It covers the default main text model `DeepSeekProvider`, the `OpenAICompatibleProvider` for any OpenAI-compatible service, the vision model `ZhipuVisionProvider`, multi-provider fallback via `FallbackProvider` and `FallbackPolicy`, and structured output via `output_schema`. It also covers streaming events, errors/timeouts/retries, security, and troubleshooting.

All code blocks come from **real, runnable** examples in the repository (`examples/`) and are linked with "View the complete runnable example"; every class, method, and field referenced actually exists in `src/super_harness`.

## 1. What this is / When to use

- **Main text model**: the default is `DeepSeekProvider` (model `deepseek-v4-flash`, `base_url` `https://api.deepseek.com`, API key read from the `DEEPSEEK_API_KEY` environment variable). Use it for most conversations, tool calls, structured output, and streaming.
- **Custom / OpenAI-compatible provider**: use `OpenAICompatibleProvider` with your own `base_url`, `model`, and `api_key_env` when you need to reach any third-party service that implements the OpenAI Chat Completions or Responses protocols (self-hosted gateways, other vendors, internal proxies).
- **Vision model**: use `ZhipuVisionProvider` (model `glm-4v-flash`, key read from `ZHIPU_VISION_API_KEY`) when the model must understand images — local files, data URLs, or HTTPS image URLs — or expose vision to the agent as the `knowledge.vision_analyze` tool via `KnowledgeRouter`.
- **Capability fallback**: use `FallbackProvider` with `FallbackPolicy` when you need to try several providers in order, switch automatically after a failure or timeout, and advertise an intersection of the whole chain's capability declarations.
- **Structured output**: use `Agent.run(..., output_schema=...)` when the model must return an object conforming to a JSON Schema instead of free text.

In short: use DeepSeek by default, `OpenAICompatible` to switch backends, Zhipu vision to "see" images, Fallback for resilience, and `output_schema` for well-formed output.

## 2. Prerequisites

- Python 3.11+ with the project installed: `pip install -e .` (run from the repository root).
- At least one valid API key, provided through the environment. The core keys:
  - `DEEPSEEK_API_KEY` — required for the main text model.
  - `ZHIPU_VISION_API_KEY` — required for the vision model (only when using vision).
  - For custom providers the key name is whatever you pass as `api_key_env`, e.g. `CUSTOM_API_KEY`.
- Keys are read from the environment **at request time** and are never written into events, logs, or code. You can put keys in `.env` (the config loader does not auto-load it unless `load_dotenv=True`) or just `export` them.
- Every provider validates its key before use; a missing key raises `ModelError` (or `VisionError` for vision).

## 3. Model provider overview

| Class | Purpose | Default model | Key environment variable |
| --- | --- | --- | --- |
| `DeepSeekProvider` | Main text model (DeepSeek official API) | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |
| `OpenAICompatibleProvider` | Any OpenAI-compatible service | set by `model` (required) | set by `api_key_env` |
| `ZhipuVisionProvider` | Vision understanding (GLM-4V) | `glm-4v-flash` | `ZHIPU_VISION_API_KEY` |
| `FallbackProvider` | Ordered fallback across providers | first provider's `model` | depends on inner providers |

All providers implement the same `ModelProvider` protocol: `name`, `capabilities`, `complete(request)`, `stream(request)`, `aclose()`. `Agent` depends only on this protocol, so any provider — including `FallbackProvider` — can be passed straight to `Agent`.

`ModelCapabilities` declares what a provider supports; `Agent` uses it to decide how to drive the model:

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `streaming` | `bool` | `True` | Supports streaming output |
| `tools` | `bool` | `True` | Supports tool calling |
| `structured_output` | `bool` | `True` | Supports structured output |
| `reasoning` | `bool` | `False` | Supports reasoning |
| `parallel_tool_calls` | `bool` | `True` | Can call several tools in one step |
| `wire_apis` | `tuple[str, ...]` | `("chat_completions",)` | Supported wire protocols (`chat_completions` / `responses`) |

## 4. Main text model: DeepSeekProvider

### 4.1 What this is / When to use

`DeepSeekProvider` is the default main text-model adapter. It subclasses `OpenAICompatibleProvider` with DeepSeek defaults preset, so `DeepSeekProvider()` just works as long as `DEEPSEEK_API_KEY` is in the environment. Use it for plain chat, tool calling, structured output, streaming, and multi-turn `Thread` sessions.

### 4.2 Quick start

```python
from super_harness import Agent, DeepSeekProvider

provider = DeepSeekProvider()
agent = Agent(provider, instructions="Answer clearly and briefly.")
response = agent.run("Explain what an agent runtime does in one sentence.")
print(response.text)
```

This is exactly `examples/01_basic_agent/main.py` — the minimal loop for running an Agent: build a provider → construct the Agent → `run` → read `response.text`. `run` opens a brand-new `Thread`; use `agent.run(...)` for one-shot Q&A and `agent.thread()` for multi-turn sessions.

### 4.3 Configuration

**Environment variables**

| Environment variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | Yes | none | DeepSeek API key; read from the environment at request time; missing raises `ModelError` |

**Constructor parameters and defaults** (all keyword-only in `DeepSeekProvider.__init__`)

| Parameter | Default | Description |
| --- | --- | --- |
| `model` | `"deepseek-v4-flash"` | Model name to use |
| `api_key` | `None` | Key passed directly; otherwise read from `DEEPSEEK_API_KEY` |
| `base_url` | `"https://api.deepseek.com"` | API root (without protocol path) |
| `wire_api` | `WireAPI.CHAT_COMPLETIONS` | Wire protocol: `CHAT_COMPLETIONS` or `RESPONSES` |
| `timeout` | `60.0` | Per-request HTTP timeout (seconds) |
| `max_retries` | `2` | Retry ceiling for non-streaming `complete` |
| `stream_max_retries` | `1` | Retry ceiling for streaming `stream` |
| `client` | `None` | An optional shared `httpx.AsyncClient` |

Preset capability declaration: `streaming=True`, `tools=True`, `structured_output=True`, `reasoning=True`, `parallel_tool_calls=True`, `wire_apis=("chat_completions", "responses")`.

### 4.4 DeepSeek V4 Flash setup and wire protocols

DeepSeek V4 Flash is the default text model. Besides the model name, `base_url` and `wire_api` determine how requests are sent:

- **`WireAPI.CHAT_COMPLETIONS` (default)**: requests go to `{base_url}/chat/completions` with an OpenAI Chat Completions payload (`messages`, `tools`, `parallel_tool_calls`, `response_format`). This is the most common and most compatible mode.
- **`WireAPI.RESPONSES`**: requests go to `{base_url}/responses` with a Responses payload (`input`, `text.format`). Tool calls and output are parsed from Responses event streams (`response.output_text.delta`, `response.function_call_arguments.delta`, `response.output_item.added`, `response.completed`).

Two DeepSeek-specific behaviors matter:

1. **`developer` role is mapped to `system`**: the DeepSeek native API rejects the OpenAI `developer` role and requires `system`. `DeepSeekProvider` rewrites `developer` to `system` during serialization; everything else stays byte-identical to OpenAI-compatible reuse.
2. **Structured output goes through `json_object`**: the DeepSeek native API rejects `response_format: json_schema` (`This response_format type is unavailable now`) and only accepts `json_object`. When `output_schema` is set and `wire_api` is `CHAT_COMPLETIONS`, the request is rewritten to `{"type": "json_object"}`; schema conformance is validated locally by the runtime after parsing (see Section 8), so relaxing the wire format is safe.

### 4.5 Basic example

`examples/01_basic_agent/main.py`:

```python
"""Minimal synchronous DeepSeek agent."""

from super_harness import Agent, DeepSeekProvider


def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider, instructions="Answer clearly and briefly.")
    response = agent.run("Explain what an agent runtime does in one sentence.")
    print(response.text)


if __name__ == "__main__":
    main()
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py)

### 4.6 Real-world example

Real applications usually need multi-turn conversation — keep history in the same `Thread` instead of opening a new one per turn. `agent.thread()` returns a reusable `Thread`; repeated `thread.run(...)` carries previous messages along:

```python
from super_harness import Agent, DeepSeekProvider

provider = DeepSeekProvider()
agent = Agent(provider, instructions="You are a data analyst. Answer with concise bullet points.")
thread = agent.thread()

first = thread.run("Summarize the top three revenue drivers of last quarter.")
print(first.text)

# The second turn carries the full context of the first
second = thread.run("How do those drivers compare to the previous quarter?")
print(second.text)
```

`Agent.thread()` and `Thread.run()` are real APIs; multi-turn context stays in memory by default. For persistence (resume after restart, forking), combine with `SQLiteThreadStore` (see User Guide Part IV: Sessions & Persistence; example `examples/07_durable_thread/main.py`).

### 4.7 Advanced example

Switch to the `WireAPI.RESPONSES` protocol and consume text deltas via streaming. `agent.astream` yields immutable `Event` objects one at a time; text arrives as `model.text.delta` events with the delta in `event.payload["delta"]`:

```python
import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import WireAPI


async def main() -> None:
    provider = DeepSeekProvider(wire_api=WireAPI.RESPONSES)
    agent = Agent(provider)
    async for event in agent.astream("Briefly explain the RESPONSES wire format."):
        if event.type == "model.text.delta":
            print(event.payload["delta"], end="", flush=True)
    print()
    await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

The full streaming pattern is in `examples/02_streaming/main.py` (detailed in Section 9 below).

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)

### 4.8 API quick reference

```python
provider = DeepSeekProvider()                                   # all defaults
provider = DeepSeekProvider(model="deepseek-v4-flash")          # explicit model
provider = DeepSeekProvider(wire_api=WireAPI.RESPONSES)         # switch wire protocol
agent = Agent(provider, instructions="...")                     # build an Agent
response = await agent.arun("Hello")                            # async, returns ModelResponse
response = agent.run("Hello")                                   # synchronous
response.text                                                   # normalized text
response.usage                                                  # Usage(input/output/total_tokens)
response.tool_calls                                             # normalized ToolCall tuple
response.output_json                                            # parsed object for structured output
await agent.aclose()                                            # close provider-owned client
```

## 5. Custom / OpenAI-compatible provider: OpenAICompatibleProvider

### 5.1 What this is / When to use

`OpenAICompatibleProvider` is a provider-neutral HTTP adapter for any service compatible with the OpenAI Chat Completions or Responses protocols: self-hosted LLM gateways, other vendors, internal proxies, compatibility layers. As long as the target accepts `Authorization: Bearer <key>` and returns the standard shapes, it can be integrated. `DeepSeekProvider` is exactly a subclass of it with DeepSeek defaults preset.

### 5.2 Quick start

```python
from super_harness import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="your-model-name",                  # required
    base_url="https://api.example.com/v1",    # required
    api_key_env="CUSTOM_API_KEY",             # env var holding the key
)
agent = Agent(provider, instructions="Answer concisely.")
print(agent.run("Hello").text)
```

### 5.3 Configuration

**Environment variables**

| Environment variable | Required | Default | Description |
| --- | --- | --- | --- |
| `CUSTOM_API_KEY` (example name) | Yes (as per `api_key_env`) | none | Named by `api_key_env`; alternatively pass `api_key` directly |

**Constructor parameters** (everything except `model` and `base_url` is keyword-only)

| Parameter | Default | Description |
| --- | --- | --- |
| `model` | (required) | Target model name |
| `base_url` | (required) | API root; trailing `/` stripped automatically |
| `api_key` | `None` | Key passed directly; takes precedence over `api_key_env` |
| `api_key_env` | `None` | Environment variable name holding the key |
| `wire_api` | `WireAPI.CHAT_COMPLETIONS` | Wire protocol selection |
| `timeout` | `60.0` | Request timeout (seconds) |
| `max_retries` | `2` | Non-streaming retry ceiling |
| `stream_max_retries` | `1` | Streaming retry ceiling |
| `client` | `None` | An optional shared `httpx.AsyncClient` |
| `name` | `"openai_compatible"` | Provider name (logs/events/errors) |
| `capabilities` | derived from `wire_api` | Capability declaration; override when needed |

**Retry semantics**: retry counts must be non-negative (otherwise `ValueError`). Retryable errors are transport errors (`httpx.TransportError`, `httpx.TimeoutException`) and HTTP 429 or 5xx; backoff is `min(0.25 * 2^attempt + jitter, 2.0)` seconds, up to `max_retries`. **Authentication errors (401/403) and other 4xx fail immediately**, never retried, and are wrapped as `ModelError` (with HTTP status in details). `ModelError` raised inside `complete` is re-raised without retry; streaming `stream` retries only when a failure happens before the terminal completion event.

### 5.4 Basic example

Talk to an OpenAI-compatible endpoint for a one-shot Q&A, with `api_key_env` so the key is read from the environment instead of being hard-coded:

```python
from super_harness import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="gpt-4o-mini",
    base_url="https://your-gateway.example.com/v1",
    api_key_env="CUSTOM_API_KEY",
)
agent = Agent(provider, instructions="Answer concisely.")
response = agent.run("What is the difference between Chat Completions and Responses?")
print(response.text)
```

### 5.5 Real-world example

Source the endpoint, model name, and key from the environment/runtime so the same code can run in dev, test, and production:

```python
import os

from super_harness import Agent, OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model=os.environ["MODEL_NAME"],
    base_url=os.environ["BASE_URL"],
    api_key_env="CUSTOM_API_KEY",
)
agent = Agent(provider, instructions="You are a technical assistant. Answer in three sentences or fewer.")
print(agent.run("Explain what an agent runtime is.").text)
```

### 5.6 Advanced example

Use the `WireAPI.RESPONSES` protocol and inject a shared `httpx.AsyncClient` with a longer timeout through `client` (connection reuse, centralized timeout management). Use `agent.arun` for async flows:

```python
import asyncio

import httpx

from super_harness import Agent, OpenAICompatibleProvider
from super_harness.models import WireAPI


async def main() -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        provider = OpenAICompatibleProvider(
            model="openai-compatible-model",
            base_url="https://api.example.com/v1",
            api_key_env="CUSTOM_API_KEY",
            wire_api=WireAPI.RESPONSES,
            client=client,
        )
        agent = Agent(provider, instructions="Answer concisely.")
        response = await agent.arun("Hello")
        print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
```

### 5.7 API quick reference

```python
provider = OpenAICompatibleProvider(model="m", base_url="https://.../v1", api_key_env="K")
provider.wire_api              # WireAPI.CHAT_COMPLETIONS | WireAPI.RESPONSES
provider.base_url              # address with trailing "/" stripped
provider.timeout / provider.max_retries / provider.stream_max_retries
provider.name                  # provider name
provider.capabilities          # ModelCapabilities
response = await provider.complete(request)   # low level: send a ModelRequest directly
async for event in provider.stream(request): # low level: stream ModelStreamEvent
await provider.aclose()
```

## 6. Vision model: ZhipuVisionProvider

### 6.1 What this is / When to use

`ZhipuVisionProvider` is the GLM-4V vision adapter. Default model `glm-4v-flash`; key read from `ZHIPU_VISION_API_KEY`. It supports three image input forms:

- **Local file path**: `Path("image.png")` or a string path. The runtime reads the file, validates the size cap (default `10_000_000` bytes), checks the image format by magic bytes (PNG/JPEG/GIF/WebP), then encodes it as a `data:` URL. Local images never leave the machine, and malformed files are never sent.
- **data URL**: `data:image/png;base64,...` is passed through as-is.
- **HTTPS / HTTP URL**: `https://...` or `http://...` is passed through as-is; the Zhipu service fetches it.

Use it for OCR, image understanding, chart reading, screenshot analysis, or exposing a "look at this image" capability to the agent as a tool.

### 6.2 Quick start

```python
import asyncio
from pathlib import Path

from super_harness import ZhipuVisionProvider


async def main() -> None:
    result = await ZhipuVisionProvider().analyze(Path("image.png"), "Describe this image")
    print(result.text)


asyncio.run(main())
```

`analyze(image, prompt)` returns a `VisionResult` whose `text` field is the model's description of the image.

### 6.3 Configuration

**Environment variables**

| Environment variable | Required | Default | Description |
| --- | --- | --- | --- |
| `ZHIPU_VISION_API_KEY` | Yes | none | Zhipu GLM-4V API key; `analyze` raises `VisionError` when missing |

**Constructor parameters** (all keyword-only)

| Parameter | Default | Description |
| --- | --- | --- |
| `api_key` | `None` | Key passed directly; otherwise read from `ZHIPU_VISION_API_KEY` |
| `endpoint` | `"https://open.bigmodel.cn/api/paas/v4/chat/completions"` | Zhipu chat endpoint |
| `model` | `"glm-4v-flash"` | Vision model name |
| `timeout` | `30.0` | Request timeout (seconds) |
| `retries` | `1` | Per-call retry count |
| `max_image_bytes` | `10_000_000` | Local image size cap (bytes) |
| `client` | `None` | An optional shared `httpx.AsyncClient` |
| `trace_sink` | `None` | Knowledge trace callback (`KnowledgeTrace`) |
| `observer` | `None` | Event observer |

**Image input validation**: local paths are checked against magic-byte signatures — only PNG/JPEG/GIF/WebP are accepted; oversized files raise `VisionError("local image exceeds size limit")`; non-image files raise `VisionError("local input is not a recognized image")`; unreadable files raise `VisionError("unable to read local image")`. An empty `prompt` raises `ValueError("vision prompt must be non-empty")`.

### 6.4 Basic example

Analyze a local image, `examples/16_vision_local.py`:

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

### 6.5 Real-world example

Analyze a remote HTTPS image (for example an online screenshot), `examples/17_vision_url.py`:

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

### 6.6 Advanced / combined example

Expose vision as an agent-callable tool. `KnowledgeRouter(vision=...)` turns the vision provider into the tool `knowledge.vision_analyze`, so the model can "look at images on demand" mid-conversation. `examples/18_vision_tool.py`:

```python
from super_harness import KnowledgeRouter, ZhipuVisionProvider

router = KnowledgeRouter(vision=ZhipuVisionProvider())
vision_tool = router.tools()[0]
print(vision_tool.qualified_name, vision_tool.provider_definition().parameters)
```

- `vision_tool.qualified_name` → `"knowledge.vision_analyze"` (namespace `knowledge` + name `vision_analyze`).
- `vision_tool.provider_definition()` → the `ToolDefinition` handed to the model (including the parameter JSON Schema).
- Pass `router.tools()` to `Agent(..., tools=router.tools())` and the model can call the vision tool.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/18_vision_tool.py)

**Batched analysis** (advanced): run `analyze` over several images in parallel with `asyncio.gather`:

```python
import asyncio
from pathlib import Path

from super_harness import ZhipuVisionProvider


async def main() -> None:
    provider = ZhipuVisionProvider()
    frames = [Path("frame_1.png"), Path("frame_2.png"), Path("frame_3.png")]
    results = await asyncio.gather(*(provider.analyze(f, "What changed?") for f in frames))
    for result in results:
        print(result.text)


asyncio.run(main())
```

### 6.7 API quick reference

```python
provider = ZhipuVisionProvider()
result = await provider.analyze(image, prompt)   # image: str | Path
result.text       # description text
result.model      # model used (default glm-4v-flash)
result.provider   # "zhipu"
router = KnowledgeRouter(vision=provider)
await router.vision(image, prompt)               # call through the router
tools = router.tools()                           # includes knowledge.vision_analyze
```

### 6.8 Events / observability

With an `observer` passed in, every `analyze` emits events (useful for cost/latency stats):

| Event type | Timing | Payload highlights |
| --- | --- | --- |
| `vision.started` | before the request | `provider`, `model`, `operation_id` |
| `vision.completed` | on success | `provider`, `model`, `operation_id`, `item_count`, `duration_ms` |
| `vision.failed` | on failure | `provider`, `model`, `operation_id`, `duration_ms`, `error_class` |

### 6.9 Errors / timeouts / retries

- Missing key: `VisionError("ZHIPU_VISION_API_KEY is required")`.
- Network/HTTP failures: `VisionError` (normalized, retried `retries` times).
- Local files: unreadable, oversized, or non-image inputs raise the corresponding `VisionError`.
- Malformed server payload: `VisionError("vision response has invalid choices")`.

## 7. Capabilities and fallback: FallbackProvider + FallbackPolicy

### 7.1 What this is / When to use

`FallbackProvider` tries a chain of providers in order: when the previous one fails (or times out, or is non-retryable), it switches to the next. Use it for primary/backup models, rate-limit switching, graceful degradation, or keeping availability when a primary service is unreachable. Unlike silent switching, **every attempt and switch is observable** (events via `observer`), and callers always know which provider answered.

`FallbackProvider.capabilities` is the **intersection of every child's capability declaration**: if any child lacks a capability (streaming, tools, structured output, reasoning, parallel tool calls), the whole chain advertises that it does not support it; `wire_apis` is the sorted intersection of the children's supported protocols. This keeps `Agent` from using a feature that some provider in the chain cannot handle.

### 7.2 Quick start

Wrap the primary and backup models in a fallback chain and hand it to `Agent`:

```python
from super_harness import Agent, DeepSeekProvider, FallbackProvider, OpenAICompatibleProvider

master = DeepSeekProvider()
backup = OpenAICompatibleProvider(
    model="backup-model",
    base_url="https://api.example.com/v1",
    api_key_env="BACKUP_API_KEY",
)
agent = Agent(FallbackProvider((master, backup)))
print(agent.run("Hello").text)
```

When the primary provider fails, `FallbackProvider.complete` automatically tries the backup and returns its result.

### 7.3 Configuration

**`FallbackPolicy`** (immutable dataclass)

| Field | Default | Description |
| --- | --- | --- |
| `timeout` | `60.0` | **Bounded timeout** per provider attempt (seconds); must be positive, otherwise `ValueError` |
| `retry_if` | `_retryable_error` | Predicate `Callable[[Exception], bool]` deciding whether an exception may fall back; defaults to `True` for `ModelError` and `TimeoutError` |

**`FallbackProvider`**

| Parameter | Default | Description |
| --- | --- | --- |
| `providers` | (required, non-empty) | Providers tried in order; empty raises `ValueError` |
| `policy` | `FallbackPolicy()` | Fallback policy |
| `observer` | `None` | Event observer |

`FallbackProvider.name` looks like `"fallback[a,b]"`; `.model` returns the first provider's `model`.

### 7.4 Basic example

Construct an explicit failing primary and a successful backup to verify the fallback behavior. `examples/81_provider_fallback.py`:

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

The output is `ok`: `primary` raises `ModelError("unavailable")`, which is retryable, so `FallbackProvider` switches to `backup` and returns its text. This demonstrates that any object implementing `complete`/`stream`/`aclose` with `name` and `capabilities` can be part of a fallback chain.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/81_provider_fallback.py)

### 7.5 Real-world example

Add a bounded timeout per provider attempt so a stuck provider does not hang forever. `examples/83_fallback_timeout.py`:

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

`SlowProvider.complete` sleeps 10 seconds, while `FallbackPolicy(timeout=0.01)` bounds each attempt at 0.01 seconds. The timeout is normalized to `ModelError` (`"model provider attempt timed out"`, details include the provider name and timeout). `TimeoutError` is retryable by default, but there is no backup here, so the error is re-raised. Output looks like:

```
ModelError model provider attempt timed out
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/83_fallback_timeout.py)

### 7.6 Advanced example

**The streaming fallback "visible output is unsafe" rule**. In streaming, `FallbackProvider` may switch to a backup only while **no visible output has been produced yet**. Once text or tool-call deltas (`TEXT_DELTA` / `TOOL_CALL_DELTA`) have streamed out, a mid-stream failure raises `ModelError("provider stream failed after visible output; fallback is unsafe")` instead of switching silently — this avoids showing the user a partial response and then duplicating it from the backup model. `examples/82_stream_fallback_safety.py` shows the primary failing **before** producing output, so the switch to the backup is safe:

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

The primary raises `ModelError` before producing any output, so the fallback is safe; the output is `['started', 'text_delta', 'completed']`.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/82_stream_fallback_safety.py)

### 7.7 API quick reference

```python
chain = FallbackProvider((a, b), policy=FallbackPolicy(timeout=30.0), observer=obs)
chain.name                      # "fallback[a,b]"
chain.model                     # first provider's model
chain.capabilities              # intersection of children's capability declarations
response = await chain.complete(request)
async for event in chain.stream(request):
    ...
await chain.aclose()            # close all children in parallel
```

### 7.8 Events / observability

With an `observer` passed in, every attempt emits events and the switching direction is visible to callers:

| Event type | Timing | Payload highlights |
| --- | --- | --- |
| `provider.attempt.started` | before trying a provider | `provider`, `attempt` (1-based) |
| `provider.attempt.completed` | a provider succeeded | `provider`, `attempt` |
| `provider.attempt.failed` | a provider failed | `provider`, `attempt`, `error_class` |
| `provider.fallback.selected` | decided to switch to next | `provider` (next), `attempt`, `previous_provider` |

### 7.9 Errors / timeouts / retries

- Every attempt runs inside `asyncio.timeout(policy.timeout)`; a timeout is normalized to `ModelError("model provider attempt timed out")`.
- Non-`ModelError`/`TimeoutError` exceptions are judged by `retry_if`; when not retryable, the normalized `ModelError` is raised immediately.
- When every provider fails: `ModelError("provider fallback exhausted", details={"attempts": [...]})`.
- Streaming: an inner stream that ends without a `COMPLETED` event raises `ModelError("provider stream ended without a completed event")`; failure after visible output raises `ModelError("provider stream failed after visible output; fallback is unsafe")`.
- Caller cancellation (`asyncio.CancelledError`) always propagates; it is never swallowed.

## 8. Structured output

### 8.1 What this is / When to use

Use `output_schema` (a JSON Schema) to constrain the model into returning a **structured JSON object** instead of free text. Use it for parsing model output into typed structures, data extraction, form filling, or feeding downstream systems directly. The return value lives in `ModelResponse.output_json`, a parsed, frozen (read-only mapping) object.

Wire-level behavior per protocol:

- **OpenAI-compatible `CHAT_COMPLETIONS`**: sends `response_format: {type: "json_schema", json_schema: {name: "super_harness_output", strict: true, schema: ...}}`.
- **OpenAI-compatible `RESPONSES`**: sends `text.format: {type: "json_schema", ...}`.
- **DeepSeek (`CHAT_COMPLETIONS`)**: the native API rejects `json_schema`, so it is rewritten to `response_format: {type: "json_object"}`; schema conformance is validated locally by the runtime after parsing (the response text is `json.loads`-ed into an object and exposed as `output_json`), so relaxing the wire format is safe.

### 8.2 Quick start

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider())
schema = {
    "type": "object",
    "properties": {
        "city": {"type": "string"},
        "temperature_c": {"type": "number"},
    },
    "required": ["city", "temperature_c"],
    "additionalProperties": False,
}
response = agent.run("Weather in Chengdu?", output_schema=schema)
print(response.output_json)
```

`response.output_json` is a read-only mapping, e.g. `{"city": "Chengdu", "temperature_c": 28.0}`.

### 8.3 Basic example

Request strict JSON and read the normalized tool calls. `examples/03_structured_and_tools/main.py`:

```python
"""Request strict JSON and normalize a provider tool call."""

import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import ToolDefinition


async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider)
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    weather = ToolDefinition(
        "weather",
        "Get current weather for a city",
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    )
    try:
        structured = await agent.arun("Summarize Chengdu in JSON.", output_schema=schema)
        print(structured.text)
        tool_response = await agent.arun("Use weather for Chengdu.", tools=[weather])
        for call in tool_response.tool_calls:
            print(call.call_id, call.name, dict(call.arguments))
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

- `output_schema` and `tools` are two independent keyword arguments of `arun`; they can be used separately or together.
- `ToolDefinition(name, description, parameters)` declares a function to the model.
- Normalized `ToolCall` values carry `call_id`, `name`, `arguments` (read-only mapping), and `raw_arguments`.

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py)

### 8.4 Real-world example

Consume `output_json` in application code, map model output into business fields, and handle the case where no object was returned:

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider())
schema = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["title", "keywords"],
    "additionalProperties": False,
}
response = agent.run("Generate a title and three keywords for this technical article.", output_schema=schema)
if response.output_json is not None:
    title = response.output_json["title"]
    keywords = list(response.output_json["keywords"])
    print(title, keywords)
else:
    print("The model did not return a structured object; text was:", response.text)
```

### 8.5 Advanced example

Build a `ModelRequest` directly at the provider layer to also control runtime fields such as `temperature` (which `Agent.run` does not expose). Use `Message` / `MessageRole` / `ModelRequest` together with `output_schema`:

```python
import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import Message, MessageRole, ModelRequest


async def main() -> None:
    agent = Agent(DeepSeekProvider())
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        "required": ["answer", "confidence"],
        "additionalProperties": False,
    }
    request = ModelRequest(
        messages=(Message(MessageRole.USER, "Summarize in JSON."),),
        output_schema=schema,
        temperature=0.0,
    )
    response = await agent.provider.complete(request)
    print(response.output_json)


if __name__ == "__main__":
    asyncio.run(main())
```

`agent.provider` is the provider passed at Agent construction; `provider.complete(ModelRequest)` goes through the same normalization path as `Agent.run`, so `output_json` is available too.

### 8.6 API quick reference

```python
response = agent.run(input, output_schema=json_schema)      # synchronous
response = await agent.arun(input, output_schema=json_schema)  # asynchronous
response.output_json      # parsed read-only mapping, or None
response.text             # raw text (the JSON string)
# temperature / extra can be set at the ModelRequest layer
```

### 8.7 Errors

- Unparseable JSON from the provider: `ModelError("provider returned invalid tool-call JSON")`.
- Non-object JSON from the provider: `ModelError("provider returned non-object tool-call arguments")`.
- DeepSeek's `json_object` only guarantees "it is JSON", not schema conformance; conformance is handled locally by `_structured` after parsing into `output_json`. Applications should validate required fields when reading.

## 9. Events & streaming

### 9.1 Provider layer: ModelStreamEvent

`provider.stream(ModelRequest)` yields `ModelStreamEvent` objects one at a time; the `type` values are:

| Type | Meaning |
| --- | --- |
| `ModelStreamEventType.STARTED` | Stream started |
| `ModelStreamEventType.TEXT_DELTA` | Text delta (`delta`) |
| `ModelStreamEventType.TOOL_CALL_DELTA` | Tool-call delta (`tool_call_index`, `tool_call_id`, `tool_name`, `delta`) |
| `ModelStreamEventType.COMPLETED` | Stream finished, carries the full `response` |

### 9.2 Agent layer: Event

`agent.astream(...)` re-wraps model events into runtime `Event` objects; `event.type` and payload:

| Event type | Payload highlights |
| --- | --- |
| `model.started` | `provider`, `model`, `step` |
| `model.text.delta` | `delta`, `step` |
| `model.tool_call.delta` | `index`, `name`, `delta`, `step` (also `Event.tool_call_id`) |
| `model.completed` | `response`, `usage`, `tool_calls`, `provider`, `model`, `step` |
| `model.failed` | `provider`, `model`, `error_type`, `message` |

### 9.3 Quick start

`examples/02_streaming/main.py` — consume text deltas and print them as they arrive:

```python
"""Stream correlated runtime events from DeepSeek."""

import asyncio

from super_harness import Agent, DeepSeekProvider


async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider)
    try:
        async for event in agent.astream("Give three concise agent safety rules."):
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
        print()
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)

### 9.4 Real-world example

Accumulate all text deltas into the full answer and read usage stats from the `model.completed` event:

```python
import asyncio

from super_harness import Agent, DeepSeekProvider


async def main() -> None:
    agent = Agent(DeepSeekProvider())
    parts: list[str] = []
    usage = None
    async for event in agent.astream("Give three concise agent safety rules."):
        if event.type == "model.text.delta":
            parts.append(event.payload["delta"])
        elif event.type == "model.completed":
            usage = event.payload["usage"]
    print("".join(parts))
    print("usage:", usage)
    await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

### 9.5 Advanced example

Consume `ModelStreamEvent` directly at the provider layer, handling both text deltas and tool-call deltas (for example streaming tool-argument accumulation or display):

```python
import asyncio

from super_harness import DeepSeekProvider
from super_harness.models import Message, MessageRole, ModelRequest, ModelStreamEventType


async def main() -> None:
    provider = DeepSeekProvider()
    request = ModelRequest(
        messages=(Message(MessageRole.USER, "Give three concise agent safety rules."),)
    )
    async for event in provider.stream(request):
        if event.type is ModelStreamEventType.TEXT_DELTA:
            print(event.delta, end="", flush=True)
        elif event.type is ModelStreamEventType.TOOL_CALL_DELTA:
            print(f"\n[tool {event.tool_call_index} {event.tool_name}] {event.delta}", end="")
    print()
    await provider.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

## 10. Errors / timeouts / retries

**Exception hierarchy**: all framework errors derive from `SuperHarnessError`; model-related errors are `ProviderError` → `ModelError` (vision `VisionError`, search `SearchError`, RAG `RAGError`). `ModelError` carries `message`, an optional `correlation_id`, and a read-only, redacted `details` mapping.

| Scenario | Behavior |
| --- | --- |
| Missing key | `ModelError("missing credential for provider <name>: set <source>")`; vision: `VisionError("ZHIPU_VISION_API_KEY is required")` |
| Network/transport errors, HTTP 429, HTTP 5xx | Retryable; backoff `min(0.25*2^attempt+jitter, 2.0)` seconds; ceiling `max_retries` (streaming: `stream_max_retries`) |
| Auth errors (401/403) and other 4xx | **Fail immediately**, wrapped as `ModelError` (HTTP status in details) |
| Per-request timeout | `timeout` parameter (default 60s); `FallbackPolicy.timeout` bounds each fallback attempt |
| `ModelError` at the provider layer | Not retried; re-raised directly |
| Entire fallback chain fails | `ModelError("provider fallback exhausted", details={"attempts": [...]})` |
| Stream ends without `COMPLETED` | `ModelError("provider stream ended without a completed event")` (inside `FallbackProvider`) |
| Stream fails after visible output | `ModelError("provider stream failed after visible output; fallback is unsafe")` |

**Cancellation**: `asyncio.CancelledError` always propagates through `FallbackProvider`; do not call synchronous methods (`run`/`stream`) inside an active event loop — use `arun`/`astream` instead.

## 11. Combining with other features

- **Fallback + vision / search / RAG**: `KnowledgeRouter` providers each have their own retries; `FallbackProvider` is for chaining multiple *text* models into a primary/backup chain. Vision is a standalone call (`analyze`) and does not participate in a `FallbackProvider` text chain, but it can be exposed to the same Agent via `KnowledgeRouter.tools()`.
- **Fallback + multi-agent**: the `AgentManager` factory returns an `Agent`, so you can use a `FallbackProvider` as the provider for every child agent, giving each one primary/backup capability (see User Guide Part V: Orchestration).
- **Structured output + fallback**: `FallbackProvider.capabilities` intersects `structured_output`; only when every child supports structured output will the Agent use `output_schema`.
- **Fallback + observability**: pass the same `observer` to both `Agent(observer=...)` and `FallbackProvider(observer=...)` to see model events (`model.*`) and fallback events (`provider.*`) in one event stream.
- **Vision + tool loop**: pass `KnowledgeRouter.tools()` (which includes `knowledge.vision_analyze`) to `Agent(tools=...)` so the model can "look at images" on demand mid-conversation.

## 12. Security notes

- **Keys are read only from environment variables or explicit parameters**, resolved at request time; never written into events, logs, or code. When logging, combine `SecretRedactor` with structured logging (see User Guide Part VIII: Observability).
- Do not put keys or tokens inside `instructions`, prompts, or tool arguments.
- Vision local images are encoded to a `data:` URL **locally**; they do not traverse intermediate networks. For remote images, use only trusted HTTPS URLs.
- For custom providers, treat `base_url` and the API key as sensitive configuration; pass the key via `api_key_env`, not command-line arguments.
- In a fallback chain, each backup provider's key is likewise resolved from its environment variable; avoid hard-coding.
- All framework errors (`ModelError`, etc.) carry redacted diagnostic metadata in `details`; no secret values are included.

## 13. Troubleshooting

| Symptom | Diagnosis |
| --- | --- |
| `ModelError: missing credential for provider deepseek: set DEEPSEEK_API_KEY` | `DEEPSEEK_API_KEY` is not set. `export DEEPSEEK_API_KEY` and retry. |
| `VisionError: ZHIPU_VISION_API_KEY is required` | Set `ZHIPU_VISION_API_KEY` before using vision. |
| `ModelError: ... model request failed with HTTP 401/403` | Wrong key or no permission; auth errors fail immediately without retry. |
| `ModelError: ... model request failed with HTTP 429/5xx` | Rate limit or server error; retried automatically; check quota/network if it persists. |
| `ModelError: provider stream ended without a completed event` | The stream never received a `COMPLETED` event; usually the server closed early or the protocol mismatches — check `wire_api` against the service. |
| DeepSeek reports `This response_format type is unavailable now` | `DeepSeekProvider` (`CHAT_COMPLETIONS`) already rewrites to `json_object`; when using a raw `OpenAICompatibleProvider` against DeepSeek, do not send `json_schema`. |
| `VisionError: local input is not a recognized image` | The local file is not a supported PNG/JPEG/GIF/WebP. |
| `VisionError: local image exceeds size limit` | The local image exceeds `max_image_bytes` (default 10 MB). |
| `ValueError: fallback timeout must be positive` | `FallbackPolicy(timeout=...)` was given a non-positive value. |
| Calling `run()` inside an event loop hangs/errors | Use `await agent.arun(...)` / `async for ... in agent.astream(...)` inside an event loop. |
| `output_json` is `None` but `text` has a value | `output_schema` was not provided, or the provider returned invalid JSON; check `output_schema` and the response text. |

## 14. Links

**Runnable examples** (cited on this page):

- [examples/01_basic_agent/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/01_basic_agent/main.py) — minimal DeepSeek agent
- [examples/02_streaming/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py) — streaming event consumption
- [examples/03_structured_and_tools/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/03_structured_and_tools/main.py) — structured output + tools
- [examples/16_vision_local.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/16_vision_local.py) — local image vision
- [examples/17_vision_url.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/17_vision_url.py) — URL image vision
- [examples/18_vision_tool.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/18_vision_tool.py) — vision tool `knowledge.vision_analyze`
- [examples/81_provider_fallback.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/81_provider_fallback.py) — provider fallback
- [examples/82_stream_fallback_safety.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/82_stream_fallback_safety.py) — stream fallback safety
- [examples/83_fallback_timeout.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/83_fallback_timeout.py) — bounded per-attempt timeout
- [examples/07_durable_thread/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py) — durable multi-turn sessions (related)

**Related pages**:

- User Guide Part I: Getting Started (minimal Agent flow)
- User Guide Part III: Context & Inputs (composing context fragments)
- User Guide Part IV: Sessions & Persistence (`SQLiteThreadStore`, `Thread`)
- User Guide Part VIII: Observability (`observer`, events, `SecretRedactor`)
- API reference: `DeepSeekProvider`, `OpenAICompatibleProvider`, `ZhipuVisionProvider`, `FallbackProvider`, `FallbackPolicy`, `ModelCapabilities`, `ModelRequest`, `ModelResponse`, `ToolDefinition`