---
id: internals-architecture
title: "Design Goals & High-Level Architecture"
sidebar_position: 1
description: Super Harness design goals, non-goals, Codex reference strategy, async-first layered architecture, runtime loop, and concurrency architecture.
---

# Design Goals & High-Level Architecture

This is chapter 1 of the Internals series. It answers two questions: **why Super Harness is designed the way it is** (design goals and non-goals) and **how it is organized as a whole** (the async-first layered architecture, the runtime loop, and the concurrency architecture). Later chapters dive into each subsystem (models & streaming, the Tool pipeline, persistence, context & compaction, RAG, memory, Skills/MCP, plugins/hooks, autonomous orchestration, deterministic workflows, observability, CLI); this chapter provides the shared skeleton for all of them.

Everything in this chapter corresponds to the real implementation under `src/super_harness/`. API signatures are given as they actually exist; behavioral descriptions match the code in `src/super_harness/agent.py`, `src/super_harness/models/`, and `src/super_harness/runtime/`.

## Design goals

Super Harness is a **self-built, Python-native, async-first agent runtime**. It is not a wrapper around any existing product; instead it uses the OpenAI Codex runtime as a **research reference** and re-implements its behavior as a Python-native layered architecture. The core design goals:

### Goal one: Python-native

- The whole runtime is built on Python 3.11+ `asyncio`; async is a first-class citizen.
- The public API offers both async (`arun` / `astream`) and sync (`run` / `stream`) entry points, but the **sync entry points are thin consumers of the async implementation** — never a second copy of the logic.
- `dataclass(frozen=True, slots=True)` defines immutable values, ruling out accidental shared mutable state across layers.
- Minimal dependencies: the model layer depends only on `httpx`; no OpenAI/vendor SDK response classes.

### Goal two: Codex-inspired, not wrapped

- Super Harness **does not call, import, or depend on** the OpenAI Codex binary or its Rust crates.
- Instead, before implementing each feature it reads a **fixed revision** of the Codex source, extracts behavioral contracts and invariants, and re-implements them in Python.
- The pinned Codex commit is recorded in `references/CODEX_PIN.md`; the source is kept as a shallow Git submodule at `references/codex/`.
- Research notes for each feature live in `docs/research/codex/`, each listing exactly which OpenAI coupling was removed.

### Goal three: OpenAI optional

- The runtime has no dependency on OpenAI account state, ChatGPT headers, prompt-cache identifiers, or the OpenAI SDK.
- `OpenAICompatibleProvider` is only an adapter that maps neutral values to either the Chat Completions or Responses **wire protocol**; both protocols are selectable by configuration and both can be swapped for any compatible implementation.
- Provider response objects never escape the provider boundary — the runtime only ever sees neutral immutable values.

### Goal four: China-ready

- Chat Completions is a first-class wire protocol because it is broadly available across China-ready OpenAI-compatible services.
- A built-in `DeepSeekProvider` supplies the official base URL (`https://api.deepseek.com`), environment variable (`DEEPSEEK_API_KEY`), and capability declaration.
- DeepSeek's native API rejects the OpenAI `developer` role, so the adapter maps `developer` to `system` during serialization; DeepSeek also rejects `response_format: json_schema`, so the adapter relaxes it to `json_object` and validates schema conformance locally.
- RAG, Web Search, and Vision are wired through separate protocols (e.g. `ZhipuWebSearchProvider` / `ZhipuVisionProvider`); see the later "external knowledge pipeline" chapter.

### Goal five: RAG as an external contract

- RAG is not a built-in implementation detail; it is an external contract between `KnowledgeRouter` and three async protocols (`WebSearchProvider`, `RAGProvider`, `VisionProvider`).
- Concrete adapters own their provider-specific HTTP shape and return immutable neutral values (`RAGDocument`, `SearchResponse`, `VisionResult`).
- Search results and RAG context are tagged `ContextKind.RAG` and rendered with user authority.

## Non-goals

Explicitly declare what is **not** done, so the design is not dragged down by "doing everything":

- **No line-by-line Rust-to-Python port of Codex.** Codex is a Rust implementation; Super Harness borrows only its behavioral contracts and invariants, not its internal structure.
- **No built-in model hosting.** No model weights are bundled or downloaded; models are always accessed remotely through a provider.
- **No built-in vector database.** The retrieval side of RAG is provided by an external service; the runtime only defines the protocol.
- **No multi-process isolation as the default.** The local Sandbox terminates the process group on cancellation but cannot constrain arbitrary child-process syscalls; full isolation is delegated to the Docker backend.
- **No silent provider fallback.** `FallbackProvider` only performs explicit, observable switching, and **never falls back once visible output has been produced** (to avoid stitching half-consumed output).
- **No hiding failures.** A stream that does not reach its terminal state is a failure that consumes the bounded retry budget, rather than being swallowed "best-effort".

## Phased evolution

The architecture was not formed all at once; it shipped in phases (this narrative is preserved from the old `website/docs/internals.md`):

- **Phase 1**: separate the three core layers (models → provider wire mapping → Agent/Thread/Turn orchestration) and establish the stream path as authoritative.
- **Phase 2**: add the deterministic `ToolRegistry` and the `ToolExecutor` pipeline (parse → validate → approve → time-bounded invoke → normalize → truncate).
- **Phase 3**: add transactional SQLite snapshot persistence, context assembly, and compaction.
- Subsequent features (RAG, memory, Skills/MCP, plugins/hooks, autonomous orchestration, deterministic workflows, observability, CLI) evolved independently under their own research notes.

## High-level architecture

The core is **async-first, three-layer separation**. The runtime depends only on the lean `ModelProvider` protocol and never on any provider SDK response class.

```
┌────────────────────────────────────────────────────────────────────┐
│  Layer 3: orchestration                                            │
│  Agent ──creates──▶ Thread ──produces──▶ Turn / TurnHandle        │
│  ordered history · lifecycle state · correlated public Event       │
└───────────────┬────────────────────────────────────────────────────┘
                │ depends only on neutral immutable values
                │ (ModelRequest / ModelStreamEvent)
┌───────────────▼────────────────────────────────────────────────────┐
│  Layer 2: wire mapping                                             │
│  OpenAICompatibleProvider ──Chat Completions / Responses──▶ HTTP   │
│  DeepSeekProvider (subclass) · FallbackProvider (decorator)        │
│  encodes neutral values into HTTP payloads, decodes replies back   │
└───────────────┬────────────────────────────────────────────────────┘
                │ backed by httpx.AsyncClient
┌───────────────▼────────────────────────────────────────────────────┐
│  Layer 1: neutral values                                           │
│  super_harness.models.types                                        │
│  Message · ToolDefinition · ToolCall · Usage · ModelRequest         │
│  ModelResponse · ModelStreamEvent · ModelCapabilities               │
│  all immutable (frozen dataclass / MappingProxyType)                │
└────────────────────────────────────────────────────────────────────┘
```

The only pass between layers is the Layer-1 immutable values. Layer 2 encodes neutral values into HTTP payloads and decodes provider replies back into neutral values; Layer 3 consumes only neutral values and emits public `Event` objects.

### Responsibilities

- **Layer 1 (`models/types.py`)**: defines the immutable values — messages, tool schemas, tool calls, usage, capabilities, requests, responses, and stream events; performs JSON validation (depth, cycles, non-finite numbers, item limits, legal tool-name characters).
- **Layer 2 (`models/openai_compatible.py` etc.)**: all implementers of the `ModelProvider` protocol. Handles auth, HTTP transport, retry/backoff, SSE parsing, terminal-state detection, and structured-output parsing.
- **Layer 3 (`agent.py` + `runtime/`)**: `Agent` holds configuration and the provider; `Thread` holds ordered history and turns; `Turn` holds one execution's state machine. Handles orchestration, context assembly, the tool loop, persistence, and event emission.

## Data model

Core immutable values (all in `super_harness/models/types.py`, `frozen=True, slots=True`):

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
    parameters: JsonObject   # frozen MappingProxyType, validated at construction

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
    extra: JsonObject = ...   # frozen to MappingProxyType at construction

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

Key points:

- **Defensive freezing.** `ModelRequest`, `ToolDefinition`, `ToolCall`, and `ModelResponse` freeze all JSON mappings through `MappingProxyType` at construction and recursively validate JSON (depth ≤ 32, no cycles, no non-finite numbers, object/array ≤ 10000 items, keys must be strings). `test_model_types.py` verifies this.
- **Tool-name constraints.** A tool name must match `^[A-Za-z][A-Za-z0-9_.-]{0,127}$`; a tool-call ID must be 1–256 characters with no control characters; raw arguments must not exceed one million characters.
- **Neutral message storage.** Assistant tool calls and tool outputs are stored as neutral `Message` values; Chat Completions receives `tool_calls` + `tool` messages, Responses receives `function_call` + `function_call_output` items (Layer 2 performs the two-way conversion).

### Runtime state objects

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

`Turn`'s state machine allows only legal transitions: `PENDING → RUNNING → COMPLETED`, or a move to `FAILED` / `INTERRUPTED` / `CANCELLED` at any point. `complete()` accepts only `RUNNING` or `WAITING_TOOL`; `start()` accepts only `PENDING`. Every Turn reaches **exactly one terminal state**.

## Runtime loop

The runtime loop lives in `Thread._astream_unobserved` (`runtime/thread.py`) and is the heart of the system. Key points:

1. **Model-step budget.** `max_model_steps` (default 8) is a bounded per-turn model-step budget that prevents unbounded tool loops. `Agent` raises `ValueError` if it is `< 1`. Each step calls the model once; if the turn is still `RUNNING`/`WAITING_TOOL` after the loop, a `ToolError("tool loop exceeded maximum of ... model steps")` is raised.
2. **Stream path authoritative.** The runtime always drives the model through `provider.stream(request)`; `arun`/`run` are thin consumers that collect the `astream` event stream into a final `ModelResponse`.
3. **Terminal events.** A provider stream only succeeds after Chat Completions' `[DONE]` or Responses' `response.completed`; if it closes before the terminal event, `_stream_once` raises `httpx.RemoteProtocolError("stream closed before terminal completion event")`, retryable within the stream retry budget.
4. **In-step event order:** `model.started` → (`model.text.delta` / `model.tool_call.delta`) → `model.completed`.
5. **Tool loop:** if the response carries `tool_calls`, append the assistant message to history, set `WAITING_TOOL`, execute tools (parallel via `asyncio.gather`, otherwise sequential), append each `tool` message to history, and return to step 1.
6. **Termination:** `turn.complete(response)` and emit `turn.completed`; `turn.failed` is emitted on exceptions; `turn.started` is emitted at the beginning.

Simplified pseudocode:

```python
async def _astream_unobserved(self, input, *, tools, output_schema):
    # validate archived / active turn / non-empty input
    # hooks: SESSION_START (first time), USER_PROMPT
    turn = Turn(input); self._active_turn_id = turn.turn_id
    self.messages.append(Message(USER, input)); turn.start()
    yield Event("turn.started", ...)
    if len(history) > compaction_threshold_chars:
        async for e in self.acompact(): yield e
    for step in range(1, self.max_model_steps + 1):
        # inject queued steering instructions
        request = self._request(tools=tools, output_schema=output_schema)
        # hooks: BEFORE_MODEL
        async for model_event in self.provider.stream(request):
            # map to model.started / model.text.delta / model.tool_call.delta / model.completed
            if completed: response = ...; break
        # hooks: AFTER_MODEL
        if response.tool_calls and self.tool_executor is not None:
            # append assistant history, set WAITING_TOOL, execute tools, append tool history
            continue
        turn.complete(response); append assistant history; self._persist()
        # hooks: TURN_END
        yield Event("turn.completed", ...); break
    if turn.status in {RUNNING, WAITING_TOOL}:
        raise ToolError(f"tool loop exceeded maximum of {self.max_model_steps} model steps")
```

Lifecycle diagram (inside one Turn, with a tool loop):

```
turn.started
   │
   ▼
┌─▶ model.started ─▶ model.text.delta / model.tool_call.delta ─▶ model.completed
│      │                                                              │
│      └────────────── BEFORE_MODEL / AFTER_MODEL hooks ──────────────┘
│      │
│      ├─ has tool_calls ─▶ tool.started ─▶ (parallel/sequential) ─▶ tool.completed / tool.failed
│      │                     │                                        │
│      │                     └─────────── back to the next model step ◀┘
│      │
│      └─ no tool_calls ─▶ turn.completed (terminal)
│
└── over max_model_steps ─▶ ToolError (turn.failed)
```

## Concurrency & cancellation

The concurrency architecture is built entirely on `asyncio`:

- **Event-loop constraint.** The sync entry points (`run`/`stream`) collect the async operation with `asyncio.run` only when **no** event loop is running; if an active loop is detected, they raise `RuntimeError("sync API cannot run inside an active event loop; use the async API")`. `test_agent_runtime.py` verifies this.
- **TurnHandle pumping.** `TurnHandle` (`runtime/handle.py`) starts `asyncio.create_task(self._pump(...))` at construction to pump `thread.astream` events into an `asyncio.Queue`, with a `_DONE` sentinel for termination; `events()` is the async consumer and `wait()` awaits the task and returns the `ModelResponse`.
- **Parallel tool execution.** Multiple tool calls in one Turn execute concurrently via `asyncio.gather` when they all declare `supports_parallel`; otherwise they run sequentially.
- **Tool timeout.** `ToolExecutor.execute` uses `asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)`; a timeout returns a `success=False` `ToolResult` (error_type=`TimeoutError`) so the model can recover, rather than aborting the whole Turn.
- **Semaphores.** In the deterministic workflow engine (`orchestration/workflow.py`), independent nodes become asyncio Tasks and are throttled through `asyncio.Semaphore(self.max_concurrency)`.
- **Conditions, not polling.** In the autonomous multi-agent manager (`orchestration/autonomous.py`), event history and completion signals use `asyncio.Condition`'s `wait()`/`notify_all()`; waiters block rather than poll.
- **Cancellation propagation.** Cancellation propagates through async generators to HTTPX — `provider.stream` is an async generator, and a consumer `break`/cancel closes the underlying HTTP stream. `OpenAICompatibleProvider._stream_once` uses `async with self._http().stream(...)`, so exiting closes the stream.
- **Interrupt vs cancel.** `TurnHandle.interrupt()` first registers the turn id via `thread.request_interrupt()` then cancels the task; when `Thread` catches `CancelledError`, it marks the turn `INTERRUPTED` if the id is in `_interrupt_turn_ids`, otherwise `CANCELLED`. These are two distinct terminal states.
- **Early consumer close.** A consumer that exits the event stream early triggers `GeneratorExit`; the Turn is marked `INTERRUPTED` (error="event stream consumer closed").

## Persistence

- `Agent` optionally accepts a `SQLiteThreadStore`; `thread()` saves the thread immediately via `store.save(thread)`.
- `SQLiteThreadStore` writes Thread snapshots into **versioned SQLite tables**, storing thread metadata, ordered messages, ordered turns, summaries, usage, timestamps, archive state, and fork lineage — all provider-neutral.
- `ThreadSnapshot` (`persistence/sqlite.py`) is the immutable snapshot: `thread_id, created_at, updated_at, instructions, archived, parent_thread_id, metadata, messages, turns, summaries`.
- `resume(thread_id)` rebuilds a `Thread` from the loaded snapshot; **recovered `pending`/`running`/`waiting_tool` turns are marked `INTERRUPTED`** (error="interrupted before resume"), never silently completed.
- `fork(thread_id)` = `resume(thread_id).fork()`, producing a new Thread with a `parent_thread_id`.
- Details live in the later persistence chapter and in `docs/research/codex/durable-thread-context-compaction.md`.

## Events & observability

- The runtime emits immutable `Event` values (`runtime/events.py`): `type, event_id, timestamp, thread_id, turn_id, agent_id, parent_agent_id, workflow_run_id, node_id, tool_call_id, trace_id, span_id, payload`. Payloads are defensively copied and exposed through a read-only mapping.
- Event types use stable dotted names: `turn.started` / `turn.completed` / `turn.failed` / `model.started` / `model.text.delta` / `model.tool_call.delta` / `model.completed` / `model.failed` / `tool.started` / `tool.completed` / `tool.failed` / `turn.steered` / `compaction.started` / `compaction.completed`.
- `EventObserver` is a minimal sync/async-compatible observation boundary: `observe(event) -> object`. `Thread.astream` calls `self.observer.observe(event)` before yielding (awaiting the result if it is awaitable).
- The observation path sits downstream of immutable lifecycle events and **never controls scheduling or provider responses**; normalization, redaction, span correlation, counting, logging, and export belong to the later observability chapter.

## Codex reference strategy

Super Harness studies **one fixed OpenAI Codex revision** before implementing equivalent runtime features, and never develops against an unspecified `main` branch.

- The pinned commit is recorded in `references/CODEX_PIN.md`: repository `https://github.com/openai/codex.git`, commit `7c6eb0eef113ddc16ae5b207ac9add364b489798` (2026-08-25, subject "Scope stop hooks for memory consolidation (#40587)").
- The reference is kept as a shallow Git submodule at `references/codex/`; verify with `git -C references/codex rev-parse HEAD`, which should print the commit above.
- Before implementing a feature, a research note must be written under `docs/research/codex/`, containing: the Codex files/tests inspected, the behavioral contract, invariants, removed OpenAI coupling, the Python-native design, and the tests to reproduce.

Research notes directly relevant to this chapter:

- `docs/research/codex/model-provider-and-streaming.md` — model providers and streaming (Layer-2 contract, terminal events, retry budget).
- `docs/research/codex/agent-runtime-thread-turn.md` — Agent/Thread/Turn orchestration (state machine, history, events, cancellation).
- `docs/research/codex/README.md` — research-note index.

Notes for the remaining subsystems (referenced by later chapters): `tool-runtime-sandbox-approval.md`, `durable-thread-context-compaction.md`, `search-rag-vision.md`, `working-and-long-term-memory.md`, `skills-and-mcp.md`, `plugins-and-hooks.md`, `autonomous-multi-agent.md`, `deterministic-workflow.md`, `hybrid-orchestration.md`, `observability-and-hardening.md`, `cli-ecosystem-ux.md`, `release-cross-cutting.md`.

## Key interfaces & classes

### `ModelProvider` (protocol, `models/base.py`)

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

The runtime depends only on this protocol — `Agent` and `Thread` type their provider as `ModelProvider` and never import a provider SDK.

### `OpenAICompatibleProvider` (`models/openai_compatible.py`)

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

- `WireAPI.CHAT_COMPLETIONS` or `WireAPI.RESPONSES` selects whether the endpoint is `/chat/completions` or `/responses`.
- Authentication failures fail explicitly **before network I/O** (`_credential()` raises `ModelError`, details carry provider and credential_source but never the key).
- Retries: `max_retries` (non-stream) + `stream_max_retries` (stream); `_retryable` retries only transport errors, timeouts, 429, and ≥500 — 4xx and auth failures are not retried; exponential backoff `min(0.25 * 2**attempt + random()*0.05, 2.0)`.
- An `httpx.AsyncClient` can be injected (deterministic tests); `_owns_client` decides whether `aclose` closes it.

### `DeepSeekProvider` (`models/deepseek.py`)

```python
DeepSeekProvider(*, model="deepseek-v4-flash", api_key=None,
    base_url="https://api.deepseek.com",
    wire_api=WireAPI.CHAT_COMPLETIONS, timeout=60.0,
    max_retries=2, stream_max_retries=1, client=None)
```

- `api_key_env="DEEPSEEK_API_KEY"`, `name="deepseek"`, `capabilities` declares `wire_apis=("chat_completions", "responses")`.
- Overrides `_message` to map `developer` to `system`; overrides `_payload` to relax `response_format` to `json_object`.

### `FallbackProvider` (`models/fallback.py`)

```python
FallbackProvider(providers: Sequence[ModelProvider], *,
    policy: FallbackPolicy | None = None, observer: EventObserver | None = None)
@dataclass(frozen=True)
class FallbackPolicy:
    timeout: float = 60.0
    retry_if: RetryPredicate = _retryable_error   # ModelError / TimeoutError
```

- `capabilities` is the **intersection** of the chain's providers (including `wire_apis`).
- Attempts run in order, each bounded by `asyncio.timeout(policy.timeout)`.
- Streaming: if a provider fails **after producing visible output** (text/tool delta or completed), it raises `ModelError("provider stream failed after visible output; fallback is unsafe")` and does **not** fall back.

### `Agent` (`agent.py`)

```python
Agent(provider: ModelProvider, *,
    instructions: str | None = None, tools: Iterable[Tool] = (),
    approval: ApprovalPolicy | None = None, hooks: HookRegistry | None = None,
    observer: EventObserver | None = None, max_model_steps: int = 8,
    context: Iterable[ContextFragment] = (), cwd: str | None = None,
    agents_loader: AgentsMdLoader | None = None, store: SQLiteThreadStore | None = None,
    compaction_threshold_chars: int = 100_000, persona: Persona | None = None)

Agent.thread() -> Thread
Agent.resume(thread_id: str) -> Thread          # requires a store, else RuntimeError
Agent.fork(thread_id: str) -> Thread
async Agent.arun(input, *, tools=(), output_schema=None) -> ModelResponse
Agent.run(input, *, tools=(), output_schema=None) -> ModelResponse
Agent.astream(input, *, tools=(), output_schema=None) -> AsyncIterator[Event]
Agent.stream(input, *, tools=(), output_schema=None) -> Iterator[Event]
async Agent.aclose() -> None
```

`Agent` is a configurable factory that creates **mutually independent** Threads; each Thread shares the agent's provider, tool registry/executor, hooks, and observer, but owns its own history and turns.

### `Thread` (`runtime/thread.py`)

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
    messages: list[Message]          # ordered history
    turns: list[Turn]                # ordered turns

    async astream(...) -> AsyncIterator[Event]
    async arun(...) -> ModelResponse
    stream(...) / run(...)           # thin sync consumers
    start(...) -> TurnHandle
    async acompact(...) / compact(...) -> tuple[Event, Event]
    archive() / fork() / request_interrupt() / queue_steering()
    async aclose()
```

`Thread` enforces a **single active Turn**: running while `_active_turn_id` is non-null raises `RuntimeError("thread already has an active turn")`.

### `TurnHandle` (`runtime/handle.py`)

```python
TurnHandle(thread, input, *, tools=(), output_schema=None)
async events() -> AsyncIterator[Event]
async wait() -> ModelResponse
async steer(instruction: str) -> None   # queued to the next model-step checkpoint
def cancel() -> None
async interrupt() -> None                # request_interrupt + cancel
```

### Exception hierarchy (`exceptions.py`)

```python
SuperHarnessError(Exception)   # message, correlation_id, details (read-only)
├── ConfigError
├── ProviderError
│   ├── ModelError · RAGError · SearchError · VisionError
├── ToolError ├── ToolValidationError
├── SandboxError
├── ApprovalDenied
├── MCPError
├── SkillError · PluginError · HookError
├── WorkflowError · MultiAgentError
└── CancelledError   # normalized cancellation visible at public boundaries
```

## Python-native redesign

This is the most fundamental divergence from Codex (Rust), mapped point-by-point in the research notes:

- **Protocol instead of trait.** `ModelProvider` is a `@runtime_checkable` Python `Protocol`; any object with the right shape can be injected (tests use a `RecordingProvider`).
- **Immutable dataclasses instead of Rust structs.** `frozen=True` + `MappingProxyType` provide value semantics and rule out the shared-mutable-state problems Rust's ownership model would otherwise prevent.
- **Async generators instead of stream iterators.** `provider.stream` is an `AsyncIterator[ModelStreamEvent]`; a consumer cancelling it closes the underlying HTTP stream — Python's generator-cancellation semantics express Codex's stream-drop semantics.
- **`asyncio` primitives instead of explicit threads/channels.** `asyncio.gather` (parallel tools), `asyncio.wait_for` (tool timeouts), `asyncio.Semaphore` (workflow throttling), `asyncio.Condition` (autonomous-agent waiting), `asyncio.create_task` + `asyncio.Queue` (TurnHandle pumping).
- **Zero vendor SDKs.** The model layer depends only on `httpx`; no OpenAI SDK, no account/session state.

## Intentional differences

Compared with Codex, the differences Super Harness deliberately makes (each recorded in a research note's "Differences and extensions"):

- **Chat Completions as a first-class wire protocol** — driven by China readiness.
- **Hard requirement on stream terminal events.** A stream succeeds only after `[DONE]` / `response.completed`; early closure is a protocol failure retried within the stream budget (the Python port of `stream_no_completed.rs`).
- **Phased delivery.** Phase 1 only normalizes tool calls; tool execution belongs to Phase 2; persistence/context belong to Phase 3. Codex couples these capabilities earlier in its architecture.
- **Sync entry points are thin consumers**, not separate implementations, and **must not run inside an active event loop**.
- **Interrupt and cancel are two terminal states**; `resume` explicitly marks unfinished turns `INTERRUPTED` rather than silently completing them.
- **No fallback after visible provider output.**
- **DeepSeek adapter layer** (`developer`→`system`, `json_object` relaxation).

## Failure model

- **Typed exceptions.** All public failures are expressed through `SuperHarnessError` subclasses carrying read-only `details` (redacted diagnostic metadata) and an optional `correlation_id`; messages never contain secrets.
- **Model-layer failures.** `OpenAICompatibleProvider` normalizes transport/HTTP/parse errors into `ModelError`; auth fails before transport; 4xx/auth are not retried, while 429/5xx/transport errors retry within budget with backoff.
- **Stream failures.** Early closure → `httpx.RemoteProtocolError` → retry within the stream budget; each in-step stream failure emits a `model.failed` event then re-raises, marking the Turn `FAILED`.
- **Tool failures do not abort the Turn.** Validation/approval/timeout/execution errors return a `success=False` `ToolResult` the model can recover from; `ToolError("tool loop exceeded ...")` is raised only when the model-step budget is exceeded.
- **Timeouts.** Provider default 60s; Fallback applies `asyncio.timeout` per attempt; each tool has its own `timeout`.
- **Cancellation.** `asyncio.CancelledError` propagates unchanged (both `ToolExecutor` and `Thread` re-raise explicitly), never mistaken for a tool failure.
- **Sync-API misuse.** Calling a sync entry point inside an active event loop raises `RuntimeError`.

## Extension points

- **New models/services:** implement the `ModelProvider` protocol; subclass `OpenAICompatibleProvider` or write a new adapter, declaring `capabilities` and `wire_apis`.
- **Provider chains:** combine providers with `FallbackProvider`; capability declarations intersect.
- **Tools:** `Tool` / the `@tool` decorator, `ToolRegistry`, `ToolExecutor` (approval, hooks, timeout, output cap are all extensible).
- **Hooks:** `HookRegistry` dispatches at session/prompt/turn/model/tool/compaction points (see the later plugins & hooks chapter).
- **Observation:** implement `EventObserver` and attach it via `Agent(observer=...)`.
- **Persistence:** `SQLiteThreadStore` is replaceable (`Agent.store`).
- **Context:** `ContextFragment` / `ContextAssembler` are injectable; `AgentsMdLoader` loads project AGENTS files.

## Tests

Test files directly relevant to this chapter (`tests/`):

- `test_agent_runtime.py` — Agent/Thread/Turn lifecycle, history accumulation, lifecycle events, cancellation, sync-API event-loop constraint, tool loop and model-step budget.
- `test_openai_compatible.py` — both wire-protocol payloads/parsing, DeepSeek defaults and capabilities, tool and strict-schema preservation, retry budget, auth failures.
- `test_model_types.py` — defensive freezing of immutable values, tool-name constraints, JSON validation.
- `test_events.py` — event immutability and fields.
- `test_exceptions.py` — exception hierarchy and redacted details.
- `test_provider_http_integration.py` — provider behavior over real HTTP transport.
- `test_deepseek_e2e.py` — DeepSeek end-to-end (requires credentials).
- `test_context_and_persistence.py` — context assembly/compaction and SQLite snapshots, resume/fork/archive.
- `test_config.py`, `test_package.py` — configuration resolution and package surface.

Test-driven development follows the "Tests to reproduce" checklists in `docs/research/codex/*.md` (e.g. the Python reproductions of `stream_no_completed` and `json_result`).

## Limitations & future work

- **The local Sandbox cannot constrain arbitrary child-process syscalls**; Shell/Python are disabled in non-full-access modes. Full isolation depends on the Docker backend.
- **Phase-1 history is in-memory**; cross-process state recovery depends on the persistence extension.
- **The sync API cannot be used inside an active event loop** — this restricts some mixing scenarios (use the async API instead).
- **No built-in model hosting / vector store / process isolation** — all intentional non-goals.
- Future directions: stronger cross-process consistency for interrupt/resume, more China-ready service adapters, and a richer `EventObserver` ecosystem with OTEL export.

Related chapters: this chapter is the Internals skeleton; later chapters expand models & streaming, tools, persistence, context & compaction, RAG, memory, Skills/MCP, plugins/hooks, autonomous orchestration, deterministic workflows, observability, and CLI. For usage, see the user guide (`website/docs/guide/`).
