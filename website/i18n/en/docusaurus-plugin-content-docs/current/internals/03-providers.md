---
id: internals-03-providers
title: "Model Provider Layer & Fallback"
sidebar_position: 3
description: The ModelProvider protocol, neutral request/response types, OpenAI-compatible wire mapping, the DeepSeek adapter, retry/backoff, and explicit fallback chains.
---

# Internals #3: Model Provider Layer & Fallback

The runtime's only dependency on model vendors is a small `ModelProvider` protocol. It **never** depends on any provider SDK's response classes: everything that crosses the provider boundary is modeled as an immutable neutral value in `super_harness.models`. This chapter digs into that layer: the protocol itself, the neutral data model, how `OpenAICompatibleProvider` maps neutral values onto the Chat Completions and Responses HTTP wire formats, `DeepSeekProvider`'s default adapter, bounded retry/backoff, and the explicit, observable, non-silent fallback chain provided by `FallbackProvider`.

This layer answers "how is a model request sent, how is it parsed, and how is it retried or switched on failure" — it does **not** answer "how is message history orchestrated, how is Turn lifecycle managed, or how are tools executed" — those are the responsibility of `Agent`/`Thread`/`Turn` (the runtime) and belong to other Internals chapters.

## 1. Responsibilities

The provider layer sits between "neutral values" and "concrete HTTP wire formats", with cleanly divided responsibilities:

| Component | File | Responsibility |
| --- | --- | --- |
| `ModelProvider` | `models/base.py` | The only async protocol the runtime depends on: `name` / `capabilities` / `complete` / `stream` / `aclose` |
| Neutral types | `models/types.py` | Immutable values: `Message`, `ToolDefinition`, `ToolCall`, `Usage`, `ModelCapabilities`, `ModelRequest`, `ModelResponse`, `ModelStreamEvent`, etc. |
| `OpenAICompatibleProvider` | `models/openai_compatible.py` | Maps neutral values to Chat Completions or Responses HTTP payloads and replies/stream events back; owns the bounded retry policy and SSE parser |
| `WireAPI` | `models/openai_compatible.py` | The two wire enums: `chat_completions` and `responses` |
| `DeepSeekProvider` | `models/deepseek.py` | DeepSeek's OpenAI-compatible adapter: official base URL, `DEEPSEEK_API_KEY`, default model & capability declarations, `developer→system` role mapping, `json_object` structured output |
| `FallbackProvider` / `FallbackPolicy` | `models/fallback.py` | An explicit multi-provider fallback chain: ordered attempts, a bounded timeout each, observable, streaming fallback only before visible output |
| Exceptions | `exceptions.py` | Unified failure surface: `SuperHarnessError` → `ProviderError` → `ModelError` |

What this layer explicitly does **not** do:

- No orchestration, no ordered history, no Turn state machine (that is `Thread`/`Turn`).
- No tool execution or approval (that is `ToolExecutor`).
- No persistence of anything (the provider layer is stateless; Thread/Workflow persistence lives elsewhere).
- No content redaction (redaction happens on a downstream observability path), but error metadata **never carries credentials**.

## 2. Data Model

Every type in `super_harness.models` is an immutable value: `@dataclass(frozen=True, slots=True)`, and every JSON-shaped field is defensively frozen into a `MappingProxyType` at construction time, so requests, responses, tool calls, and usage cannot be accidentally mutated anywhere, including in concurrent environments.

### 2.1 Messages and roles

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

The `developer` role is the default system-instruction role in a neutral request (`Thread._request` assembles `Agent.instructions` as `Message(MessageRole.DEVELOPER, ...)`). How it is presented to an OpenAI-compatible service is decided by the adapter — the standard wire sends it verbatim, while the DeepSeek adapter maps it to `system` (see §10).

### 2.2 Tool definitions and tool calls

```python
@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: JsonObject          # Mapping[str, Any] (frozen)

@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: JsonObject           # parsed arguments object (frozen)
    raw_arguments: str              # unparsed raw argument string, for verbatim replay
```

Enforced at construction time:

- A tool name must match `^[A-Za-z][A-Za-z0-9_.-]{0,127}$` (1–128 safe characters), otherwise `ValueError`.
- `ToolCall.call_id` must be 1–256 characters with no control characters.
- `ToolCall.raw_arguments` must not exceed 1,000,000 characters.
- All JSON objects pass `_validate_json`: nesting depth ≤ 32, no non-finite floats (`nan`/`inf`), no cycles, object keys must be strings, and ≤ 10,000 fields/array items.

`raw_arguments` exists so tool-call arguments can be replayed verbatim and losslessly: the wire layer parses them into `arguments` for validation while keeping the raw string to stuff back into `messages` unchanged on later requests (see §3 and the test `test_tool_history_maps_to_each_wire_format`).

### 2.3 Usage

```python
@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
```

`_usage` normalizes the field names across wire formats: `prompt_tokens`/`input_tokens` → `input_tokens`, `completion_tokens`/`output_tokens` → `output_tokens`, and `total_tokens` falls back to their sum when absent.

### 2.4 Capability declaration

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

The capability declaration lets the runtime know "what this chain supports" without probing. `FallbackProvider.capabilities` takes the **intersection** of the whole chain (see §11).

### 2.5 Request and response

```python
@dataclass(frozen=True, slots=True)
class ModelRequest:
    messages: Sequence[Message]
    tools: Sequence[ToolDefinition] = ()
    output_schema: JsonObject | None = None
    temperature: float | None = None
    parallel_tool_calls: bool = True
    extra: JsonObject = field(default_factory=_freeze)   # extra keys passed through to the payload

@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = field(default_factory=Usage)
    response_id: str | None = None
    finish_reason: str | None = None
    output_json: JsonObject | None = None
```

Key points:

- `output_schema` is an **optional strict JSON Schema**. When set, the adapter requests structured output and `_structured` parses `text` into `output_json` before returning.
- `extra` lets the caller inject provider-specific extra payload keys, merged into the body via `payload.update(request.extra)` at the end.
- `ModelResponse` references no SDK types: only plain `str` / `tuple` / `Usage` / `JsonObject`.

### 2.6 Stream events

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

The stream path is authoritative (see §3). The event-sequence contract is:

```
STARTED → (TEXT_DELTA | TOOL_CALL_DELTA)* → COMPLETED(response=ModelResponse)
```

The `COMPLETED` event carries the final normalized `ModelResponse`. A `TOOL_CALL_DELTA` carries the accumulated tool-call identity (`tool_call_index`, `tool_call_id`, `tool_name`) and the current `delta`.

## 3. Lifecycle

### 3.1 Construction and the HTTP client

`OpenAICompatibleProvider` performs no network I/O at construction. The HTTP client is created **lazily**:

```python
def _http(self) -> httpx.AsyncClient:
    if self._client is None:
        self._client = httpx.AsyncClient(timeout=self.timeout)
    return self._client
```

- `timeout` defaults to 60.0 seconds, applied as the `httpx.AsyncClient(timeout=...)` overall timeout.
- An external `httpx.AsyncClient` can be injected (for deterministic tests, e.g. `httpx.MockTransport` or a local `ThreadingHTTPServer`); when injected, `_owns_client=False` and `aclose()` does not close it.

### 3.2 `complete()` sequence

The non-streaming path:

```
Caller                     OpenAICompatibleProvider            httpx.AsyncClient
  |  complete(request)           |                                  |
  |----------------------------->|  _credential()  env or explicit api_key
  |                              |  _endpoint()    /chat/completions or /responses
  |                              |  _payload(request, stream=False)
  |                              |  _headers()     Authorization: Bearer <key>
  |                              |--------------------------------->|  POST
  |                              |<---------------------------------|  200 JSON
  |                              |  _normalize(data)   per-wire parse
  |                              |  _structured(...)   parse text → output_json
  |<-----------------------------|  ModelResponse
```

`complete()`'s retry loop (`max_retries` defaults to 2, i.e. at most 3 POST attempts) wraps the body above; see §11.

### 3.3 `stream()` sequence and the authoritative terminus

```
Caller                OpenAICompatibleProvider               httpx.AsyncClient
  |  stream(request)       |                                  |
  |----------------------->|  yield STARTED                   |
  |                        |  _stream_once(...)  (retryable within stream budget)
  |                        |--------------------------------->|  POST stream=True
  |<-----------------------|  TEXT_DELTA / TOOL_CALL_DELTA    |  SSE: data: {...}
  |                        |    (accumulate text / tool_call state in memory)
  |                        |<---------------------------------|  data: [DONE]
  |                        |    or Responses response.completed
  |                        |  assemble ToolCall / Usage / output_json
  |<-----------------------|  COMPLETED(response=result)
```

Whether a stream succeeded is decided by the **terminal completion event**:

- For Chat Completions, success requires reading `data: [DONE]`.
- For Responses, success requires a `type: "response.completed"` event.

If the HTTP response closes early without ever producing a terminal event, `_stream_once` raises `httpx.RemoteProtocolError("stream closed before terminal completion event")`. This is a **retryable protocol failure** retried within the configured stream budget (`stream_max_retries` defaults to 1, i.e. at most 2 stream passes). The test `test_incomplete_stream_is_an_error` verifies this.

### 3.4 `aclose()` and shutdown

```python
async def aclose(self) -> None:
    if self._client is not None and self._owns_client:
        await self._client.aclose()
    self._client = None
```

Only a client that the provider created itself is closed; an injected client is the caller's responsibility.

### 3.5 How the runtime consumes it (authoritative stream path)

`Thread._astream_unobserved` calls **only `self.provider.stream(request)`**, never `complete()` — streaming is the authoritative path. It maps neutral stream events onto runtime events (see §7). This means even a simplified provider that only implements `complete()` will never be driven by the runtime; anything the runtime drives must implement `stream()`.

## 4. Key Interfaces / Classes

### 4.1 The protocol: `ModelProvider`

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

Note that `stream` is a method returning an **async generator** (`def stream(...) -> AsyncIterator[...]`), not `async def`. This is intentional: the caller obtains the generator without an extra `await`, and the generator body can `yield STARTED` as its first event. The protocol is `@runtime_checkable`, so duck-type checks with `isinstance` work.

### 4.2 The wire enum: `WireAPI`

```python
class WireAPI(StrEnum):
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"
```

### 4.3 The adapter: `OpenAICompatibleProvider`

Constructor signature (all keyword-only):

```python
OpenAICompatibleProvider(
    *,
    model: str,                       # required
    base_url: str,                    # required
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

Public attributes/methods: `name`, `capabilities`, `model`, `base_url`, `wire_api`, `timeout`, `max_retries`, `stream_max_retries`, `complete`, `stream`, `aclose`. Key internal hooks (overridable by subclasses, exactly as `DeepSeekProvider` does):

```python
_message(message: Message) -> dict          # neutral message → wire message
_payload(request, *, stream) -> dict        # neutral request → HTTP payload
_responses_inputs(messages) -> list[dict]   # neutral messages → Responses input items
_normalize(data) -> ModelResponse           # wire response → neutral response
_structured(response, request) -> ModelResponse  # text → output_json
_retryable(exc) -> bool                     # is this exception retryable
_error(exc) -> ModelError                   # normalize an error
_credential() -> str                        # obtain the credential (raise if missing)
_endpoint() -> str                          # build the URL
```

### 4.4 The default adapter: `DeepSeekProvider`

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

It subclasses `OpenAICompatibleProvider` and overrides only three things:

1. Default model `deepseek-v4-flash`, official base URL, `api_key_env="DEEPSEEK_API_KEY"`, `name="deepseek"`.
2. A capability declaration naming both wire formats: `wire_apis=("chat_completions", "responses")`, and declares `reasoning=True`.
3. Overrides `_message` (`developer → system`) and `_payload` (structured output switches to `json_object`).

### 4.5 Fallback: `FallbackProvider` and `FallbackPolicy`

```python
RetryPredicate = Callable[[Exception], bool]

@dataclass(frozen=True, slots=True)
class FallbackPolicy:
    timeout: float = 60.0
    retry_if: RetryPredicate = _retryable_error   # default: isinstance(error, (ModelError, TimeoutError))

FallbackProvider(
    providers: Sequence[ModelProvider],
    *,
    policy: FallbackPolicy | None = None,
    observer: EventObserver | None = None,
)
```

`FallbackProvider.name` returns `"fallback[" + ",".join(provider names) + "]"`; the `model` property returns the first provider's `model` (read by runtime events).

## 5. Concurrency / Cancellation

- **Shared client**: each provider holds a single `httpx.AsyncClient`, which is thread-safe, so the same provider can safely issue concurrent `complete`/`stream` calls.
- **Cancellation propagates through the async generator**: `stream()` is an async generator; when the caller stops iterating (an interrupted `async for`, `aclosing`, or task cancellation), HTTPX closes the corresponding HTTP response stream and the underlying connection is released. The `httpx` `stream()` context manager correctly closes the response when the generator is closed/cancelled.
- **The runtime does not normalize cancellation**: `Thread._astream_unobserved` re-raises `asyncio.CancelledError` (`except asyncio.CancelledError: raise`), propagating it as-is rather than wrapping it into a `ModelError` or `TurnStatus.FAILED`. Task cancellation is a **terminal state** (`TurnStatus.CANCELLED`), distinct from failure (`FAILED`) or interruption (`INTERRUPTED`).
- **Fallback does not swallow cancellation**: `FallbackProvider.complete`/`stream` catch only ordinary exceptions with `except Exception`; `asyncio.CancelledError` derives from `BaseException` and is not caught, so the `asyncio.timeout` context propagates cancellation to the executing child provider. The test `test_fallback_timeout_and_cancellation_are_distinct` verifies that "a timeout causes fallback, while cancellation raises `asyncio.CancelledError`".

## 6. Persistence (Not Applicable)

The provider layer has **no persistent state**: no database writes, no caching, no cross-request state. Credentials come from constructor args or environment variables (read per request via `_credential()`); the HTTP client is a process-local resource released by `aclose()`. Anything that must persist — Thread metadata, ordered messages, Turns — is owned by `SQLiteThreadStore` at the runtime layer (see the corresponding Internals chapter), which knows nothing about the provider, so persistence can be swapped freely without touching this layer.

## 7. Events / Observability

### 7.1 The fallback chain's own events

`FallbackProvider` accepts an optional `EventObserver` (the minimal protocol in `runtime/events.py`, `observe(event) -> object`, whose return may be awaitable and is then awaited). It emits four event types in order, and payloads never contain credentials:

| Event type | payload keys | When |
| --- | --- | --- |
| `provider.attempt.started` | `provider`, `attempt`(1-based) | each attempt begins |
| `provider.attempt.completed` | `provider`, `attempt` | an attempt returns successfully |
| `provider.attempt.failed` | `provider`, `attempt`, `error_class` | an attempt raised |
| `provider.fallback.selected` | `provider`(next), `attempt`, `previous_provider` | a fallback to the next provider is decided |

The test `test_fallback_complete_is_observable_and_ordered` asserts the exact sequence `attempt.started → attempt.failed → fallback.selected → attempt.started → attempt.completed`.

### 7.2 The runtime's remapping of provider stream events

`Thread` maps neutral stream events onto runtime events correlated by `thread_id`/`turn_id`/`step`:

| Neutral event | Runtime event | payload |
| --- | --- | --- |
| `STARTED` | `model.started` | `provider`, `model`, `step` |
| `TEXT_DELTA` | `model.text.delta` | `delta`, `step` |
| `TOOL_CALL_DELTA` | `model.tool_call.delta` | `index`, `name`, `delta`, `step` (and sets the `tool_call_id` correlation field) |
| `COMPLETED` | `model.completed` | `response`, `usage`, `tool_calls`, `provider`, `model`, `step` |
| (stream raised) | `model.failed` | `provider`, `model`, `step`, `error_class`, `message` |

`model.completed` is where the runtime accumulates model usage and tool calls (`AgentManager` accumulates usage from every `model.completed` event). `provider` reads `self.provider.name`, `model` reads `getattr(self.provider, "model", None)`, so a `FallbackProvider`'s `name` (shaped like `fallback[a,b]`) appears in events and `model` resolves to the head provider's model name.

## 8. Codex Reference

The design basis for this layer is recorded in `docs/research/codex/model-provider-and-streaming.md`. The Codex (Rust) source files it inspected include:

- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/model-provider/src/provider.rs`
- `codex-rs/codex-api/src/common.rs`
- `codex-rs/core/src/client_common.rs`
- `codex-rs/core/src/client.rs`
- `codex-rs/protocol/src/models.rs`

Its recorded **behavioral contract** (implemented point-for-point by this layer):

- A provider describes its endpoint, authentication source, wire protocol, capabilities, retry limits, and stream idle timeout.
- Requests carry normalized messages, tools, parallel-tool preference, and an optional strict JSON schema.
- Streaming produces structured lifecycle, delta, item, usage, and terminal events.
- A stream that closes before its terminal completion event is an error and can consume the bounded stream retry budget.
- Authentication errors are explicit. Empty or missing credential environment variables fail before network I/O.
- Dropping or cancelling a stream cancels downstream work.

Its recorded **invariants** (upheld by this layer):

- Retry counts and timeouts are bounded.
- Authentication failures and invalid requests are not retried.
- Provider response objects do not escape the provider boundary.
- Tool calls preserve provider call IDs and arguments.
- JSON schemas are transmitted without lossy rewriting.
- A terminal completion event is required for successful streaming.

For the related runtime chapter (Agent/Thread/Turn orchestration), see `docs/research/codex/agent-runtime-thread-turn.md`.

## 9. Python-Native Redesign

Porting Codex's Rust design to Python involved the following mapping:

- **`provider-info` struct → `ModelCapabilities` + constructor args**: endpoint, auth source, wire protocol, timeout, and retry limits are declared by the constructor; capabilities are declared explicitly as `ModelCapabilities`.
- **Rust trait/provider → async `Protocol`**: `ModelProvider` is a `@runtime_checkable` `typing.Protocol`; duck typing suffices, no inheritance required.
- **Immutable request/response values → `@dataclass(frozen=True, slots=True)` + `MappingProxyType` freezing**: requests/responses cannot be mutated under concurrency or across multi-step tool loops.
- **Explicit bearer auth → `_credential()` preflight**: credential presence is checked before any network I/O; a missing credential raises `ModelError` (see `test_missing_credential_fails_before_transport`).
- **Structured streaming events → `ModelStreamEvent` enum**: `STARTED/TEXT_DELTA/TOOL_CALL_DELTA/COMPLETED` map one-to-one onto Codex's "lifecycle, delta, item, usage, terminal" events.
- **Terminal completion requirement → `[DONE]`/`response.completed` gate**: early closure is a retryable protocol error.
- **OpenAI SDK coupling removed**: this layer does not depend on OpenAI authentication managers, account state, ChatGPT headers, prompt-cache identifiers, or OpenAI SDK response classes. Chat Completions and Responses are both wire adapters behind one provider-neutral protocol.

## 10. Intentional Differences

- **Chat Completions is a first-class wire format**: because it is broadly available across China-ready OpenAI-compatible services, it is the default wire (`WireAPI.CHAT_COMPLETIONS`) rather than a second-class compatibility layer.
- **DeepSeek `developer → system` mapping**: DeepSeek's native API rejects the OpenAI `developer` role and requires `system`; `DeepSeekProvider._message` makes only this one change, and the rest of the OpenAI-compatible reuse stays byte-identical.
- **DeepSeek structured output uses `json_object` instead of `json_schema`**: DeepSeek's native API returns `"This response_format type is unavailable now"` for `response_format: json_schema` and accepts only `json_object`. Because `_structured` validates schema conformance locally after parsing (turning `text` into `output_json`), relaxing to `json_object` is safe.
- **Error metadata never carries credentials**: normalized `ModelError.details` contains only `provider` and `status_code` etc., never the request key.
- **The provider owns its HTTP client lifecycle and also accepts injection**: injected clients make deterministic tests (`httpx.MockTransport`, a local HTTP server) possible.
- **Fallback is explicit and observable**: `FallbackProvider` does not silently swap providers; it attempts in order, emits events, and **refuses** to fall back after a stream has produced visible output (see §11).
- **Cancellation is not normalized**: task cancellation always propagates as `asyncio.CancelledError`, never wrapped as a failure.

## 11. Failure Model

### 11.1 Exception hierarchy

```
SuperHarnessError
└── ProviderError
    └── ModelError
```

`ModelError` carries `message` (a human-readable description with no secrets), `correlation_id`, and `details` (a read-only `MappingProxyType` of redacted diagnostic metadata).

### 11.2 Credential failure

`_credential()` prefers an explicit `api_key`, otherwise reads the `api_key_env` environment variable; when missing or blank it raises `ModelError` **before any network I/O**:

```
missing credential for provider deepseek: set DEEPSEEK_API_KEY
```

with `details={"provider": ..., "credential_source": ...}`. Credential failures are not retried.

### 11.3 Retryability classification and bounded backoff

`OpenAICompatibleProvider._retryable(exc)`:

| Exception | Retryable? |
| --- | --- |
| `httpx.TransportError` (incl. `RemoteProtocolError`, connection errors) | ✅ |
| `httpx.TimeoutException` | ✅ |
| `httpx.HTTPStatusError` with status `429` or `>= 500` | ✅ |
| Other `HTTPStatusError` (4xx, 401, 403, etc.) | ❌ |
| `ModelError` (parse/structured failure) | ❌ (re-raised directly) |
| Invalid JSON / `ValueError` | ❌ |

Backoff formula (`_backoff`):

```python
await asyncio.sleep(min(0.25 * (2 ** attempt) + random.random() * 0.05, 2.0))
```

Exponential backoff with a small random jitter, capped at 2.0 seconds. Budgets are bounded: `max_retries` for non-streaming (default 2 → at most 3 POSTs), `stream_max_retries` for streaming (default 1 → at most 2 stream passes).

### 11.4 The fallback chain

`FallbackProvider`'s failure model is governed by `FallbackPolicy`:

- **Bounded timeout per attempt**: `asyncio.timeout(self.policy.timeout)` (default 60.0s); a timeout raises `TimeoutError`.
- **`retry_if` predicate**: default `_retryable_error`, i.e. `isinstance(error, (ModelError, TimeoutError))`. Note it applies to the **raw exception**: transport/429/5xx inside a provider have already been normalized into `ModelError` by the adapter, so they fall back; an unexpected programming bug (e.g. `ValueError`) is not retryable and `backup` is never used (see `test_fallback_does_not_hide_unexpected_provider_bug`).
- **Error normalization**: a `ModelError` passes through unchanged; a `TimeoutError` → `ModelError("model provider attempt timed out", details={provider, timeout})`; anything else → `ModelError("model provider attempt failed", details={provider, error_class})`.
- **Chain exhausted**: when every provider fails, raise `ModelError("provider fallback exhausted", details={"attempts": [{"provider", "error"}...]})`.

**The streaming fallback safety gate** (`stream`): `FallbackProvider` tracks `visible` — set once a `TEXT_DELTA`/`TOOL_CALL_DELTA`/`COMPLETED` appears. If a provider fails after visible output, fallback is unsafe:

```
provider stream failed after visible output; fallback is unsafe
```

No switch to the next provider occurs; a `ModelError` is raised directly (see `test_fallback_stream_before_output_and_never_after_visible_output`). If the failure happens before any visible output, fallback to the next provider is allowed. Streaming fallback only happens "before output starts", so a half-answered message is never suddenly replaced.

### 11.5 Three runnable examples

**Basic: fall back after an explicit failure** ([View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/81_provider_fallback.py)):

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

**Real-world: stream from a backup only when the first provider emitted no visible output** ([View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/82_stream_fallback_safety.py)):

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

**Advanced/combined: a bounded timeout per attempt** ([View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/83_fallback_timeout.py)):

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

## 12. Extension Points

1. **Implement the `ModelProvider` protocol**: any object with `name`/`capabilities`/`complete`/`stream`/`aclose` can be passed as a provider to `Agent(...)` or `FallbackProvider(...)`. The protocol is `@runtime_checkable`, so duck typing works.
2. **Inject an `httpx.AsyncClient`**: use `httpx.MockTransport` or a local `ThreadingHTTPServer` for deterministic/integration tests; the provider only closes a client it created itself.
3. **Subclass `OpenAICompatibleProvider`**: like `DeepSeekProvider`, override `_message`/`_payload` to accommodate vendor quirks (role mapping, structured-output format, extra headers/fields); the rest of the logic is reused for free.
4. **`WireAPI` selection**: for any OpenAI-compatible endpoint, pick `wire_api=WireAPI.RESPONSES` or `CHAT_COMPLETIONS` to choose the wire format.
5. **Custom `FallbackPolicy.retry_if`**: replace the default "`ModelError`/`TimeoutError`" predicate to tailor fallback conditions by exception type.
6. **Inject an `EventObserver`**: subscribe to `provider.attempt.*` / `provider.fallback.selected` events and wire them into an existing observability pipeline.
7. **`ModelRequest.extra`**: inject provider-specific request payload keys without modifying adapter code.

## 13. Tests

The provider layer is covered by four test suites:

**`tests/test_openai_compatible.py`** — the adapter and wire mapping:

| Test | Verifies |
| --- | --- |
| `test_deepseek_defaults_and_capabilities` | DeepSeek default model, base URL, dual-wire capability declaration |
| `test_missing_credential_fails_before_transport` | missing credential raises `ModelError` before transport; no network call |
| `test_chat_payload_and_tool_call_normalization` | Chat payload preserves strict schema & tools; tool calls normalize to neutral `ToolCall`; usage normalizes |
| `test_responses_payload_and_response_normalization` | Responses payload `text.format`; `output_json` parsing; usage normalization |
| `test_tool_history_maps_to_each_wire_format` | the same tool history maps to `function_call` + `function_call_output` (Responses) |
| `test_responses_stream_normalizes_text_tool_and_json` | Responses SSE deltas assemble into one response and require `response.completed` |
| `test_retry_is_bounded_and_only_for_retryable_status` | 500 retries within budget and eventually succeeds; attempt count is bounded |
| `test_chat_stream_requires_done_and_normalizes_tool_deltas` | Chat stream accumulates tool calls per index and requires `[DONE]` |
| `test_incomplete_stream_is_an_error` | an early-closed stream is an error |

**`tests/test_model_types.py`** — the data model:

| Test | Verifies |
| --- | --- |
| `test_request_defensively_freezes_inputs` | `output_schema`/`tools` are frozen at construction; mutating the original dict does not affect the request |
| `test_messages_are_immutable` | messages are immutable (`FrozenInstanceError`) |
| `test_tool_name_must_be_non_empty` | an invalid tool name raises `ValueError` |

**`tests/test_provider_http_integration.py`** — real local HTTP integration (`@pytest.mark.integration`, via `ThreadingHTTPServer`):

- `test_complete_and_stream_over_real_local_http`: runs `complete` + `stream` against a real local endpoint and drives the full `Agent`/`Thread` runtime; asserts the final `ModelResponse.text == "local stream"`, `usage.total_tokens == 4`, and that 3 requests were received.
- `test_agent_tool_loop_over_real_local_http`: runs an entire tool loop over a real local SSE endpoint (assistant `tool_calls` → `tool` result → final `42`); asserts the second request's `messages` role sequence is `["user", "assistant", "tool"]` and the `tool_call_id` is correct.

**`tests/test_release_crosscutting.py`** — the fallback chain:

| Test | Verifies |
| --- | --- |
| `test_fallback_complete_is_observable_and_ordered` | `complete` is observable and ordered; exact event sequence; `aclose` closes every provider |
| `test_fallback_stream_before_output_and_never_after_visible_output` | fallback before output is fine; fallback after visible output is unsafe and `backup` is never called |
| `test_fallback_timeout_and_cancellation_are_distinct` | a timeout falls back to the backup; task cancellation propagates as `asyncio.CancelledError` |
| `test_fallback_does_not_hide_unexpected_provider_bug` | a non-`retry_if` exception (programming bug) is not hidden and does not trigger `backup` |

## 14. Limitations / Future Work

- **No separate stream idle timeout**: Codex documents a "stream idle timeout", but the current Python implementation uses the overall `httpx.AsyncClient(timeout=...)` timeout; there is no explicit idle timer for a stalled stream. A future improvement could add an explicit idle timeout for the SSE read interval.
- **DeepSeek structured output is locally guaranteed**: the server receives `json_object` rather than strict `json_schema`, so schema conformance relies on local `_structured` parsing. Server-side strict validation awaits native `json_schema` support from DeepSeek.
- **Fallback is linear, with no health/load awareness**: `FallbackProvider` only tries providers in declaration order; there is no latency-, success-rate-, or circuit-breaker-based routing, nor budget-based (e.g. token-budget) provider selection.
- **No SDK/native backends**: this layer is HTTP-only (OpenAI-compatible wires); no gRPC or official-SDK adapters are provided.
- **Usage may be zero until the terminal event**: for Chat Completions, usage usually arrives in the final chunk; if intermediate chunks carry no usage and there is no terminal usage, `Usage` keeps default values. Structured streams (`_stream_once`) take the terminal event's usage as authoritative.
- **`output_json` is populated only when `output_schema` is set**: a pure tool-call response has empty `text`, non-empty `tool_calls`, and `output_json = None`.
- **`parallel_tool_calls` is a declaration, not a hard constraint**: capability and request both declare parallel tool calls, but whether they actually run in parallel depends on the provider.
- **`complete()` is "authoritative" only for direct callers, since the runtime uses `stream()` exclusively**: the runtime only consumes the stream path, so `complete()` is valuable only to users/tools that call it directly; a future change could let the runtime take `complete()` in non-streaming scenarios to avoid SSE overhead.
