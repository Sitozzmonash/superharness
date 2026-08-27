---
id: internals-thread-turn
title: "Thread / Turn Model & Runtime"
sidebar_position: 2
description: Internals of the Thread/Turn lifecycle, event model, streaming, context fragments, compaction, and cancellation/steering.
---

# Thread / Turn Model & Runtime

> This page answers "how the runtime works internally and why it is designed this way." For "how to use it," see the user guide. This page focuses on principles, not operational tutorials.
> Supporting research evidence lives in `docs/research/codex/agent-runtime-thread-turn.md`, `docs/research/codex/durable-thread-context-compaction.md`, and `docs/research/codex/model-provider-and-streaming.md`, mirrored under `references/codex/`.

## 1. Responsibilities

The runtime (`super_harness/runtime/`) splits one conversation into two layers: **Thread** and **Turn**. Their responsibilities differ:

- **Thread** owns one Agent session's ordered history: the message list, the Turn list, context fragments, summaries, compaction thresholds, the tool registry and executor, hooks and the event observer, and an optional persistence store. It is the "container of state" and orchestrates without itself calling the model.
- **Turn** represents one user-initiated execution and its terminal diagnostics: input, state machine, timestamps, the final response, and error. It is the "record of one execution."
- **Event** values are immutable structured observations that expose lifecycle without requiring clients to inspect internal state.
- **TurnHandle** is the event and control handle for an active Turn: it consumes the same authoritative event stream and supports `steer`, `cancel`, and `interrupt`.

Core invariants:

1. History order is stable and append-only during a basic in-memory run.
2. Exactly one terminal state is recorded per Turn.
3. Failed or cancelled Turns retain diagnostic state (the `error` field and timestamps); they never vanish silently.
4. Model delta events precede the `model.completed` event; a Turn completes only after provider completion.
5. The streaming path is authoritative: non-streaming collection (`run`/`arun`) is a thin consumer of it.
6. Public sync wrappers (`stream`/`run`) must not nest an event loop.

The runtime depends on the small `ModelProvider` protocol and never on provider SDK response classes. Thread and Turn store provider-neutral messages and model results — no Responses API objects, OpenAI item variants, account metadata, or transport session state.

## 2. Data model

### 2.1 TurnStatus

`super_harness/runtime/turn.py` defines `TurnStatus` (a `StrEnum`) with seven states, four of which are terminal:

```python
class TurnStatus(StrEnum):
    PENDING = "pending"            # created, not yet start()ed
    RUNNING = "running"            # started; executing model/tool orchestration
    WAITING_TOOL = "waiting_tool"  # tool calls received; awaiting tool results
    COMPLETED = "completed"        # terminal: finished with a final ModelResponse
    FAILED = "failed"              # terminal: an exception was raised
    INTERRUPTED = "interrupted"    # terminal: explicitly interrupted (interrupt / early stream close / resumed in-flight turn)
    CANCELLED = "cancelled"        # terminal: cancelled (cancel)
```

Transitions are enforced by the methods on `Turn`:
- `start()`: only `PENDING` may start → sets `RUNNING` and records `started_at`.
- `complete(response)`: only `RUNNING` or `WAITING_TOOL` may complete → sets `COMPLETED`, records the response and `completed_at`.
- `fail(error)`: sets `FAILED`, records `error` and `completed_at`.
- `cancel()`: sets `CANCELLED`, records `completed_at`.

### 2.2 Turn

```python
@dataclass(slots=True)
class Turn:
    input: str
    turn_id: str = field(default_factory=lambda: str(uuid4()))
    status: TurnStatus = TurnStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    response: ModelResponse | None = None
    error: str | None = None
```

`Turn` uses UTC timestamps (`datetime.now(UTC)`); `response` is a provider-neutral `ModelResponse` and `error` is a string diagnostic.

### 2.3 Event

`super_harness/runtime/events.py` defines a frozen event. All correlation fields are optional so the same base model represents thread, turn, tool, subagent, and workflow events:

```python
@dataclass(frozen=True, slots=True)
class Event:
    type: str
    event_id: str = field(default_factory=_new_event_id)   # uuid4
    timestamp: datetime = field(default_factory=_utc_now)  # datetime.now(UTC)
    thread_id: str | None = None
    turn_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    workflow_run_id: str | None = None
    node_id: str | None = None
    tool_call_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=_empty_payload)
```

`__post_init__` applies three validation/freezing rules:
1. `type` must be a non-empty string.
2. `timestamp` must be timezone-aware, otherwise it is rejected.
3. `payload` is defensively copied and exposed as a read-only `MappingProxyType` — callers cannot mutate it.

The observation boundary `EventObserver` is a minimal protocol, sync/async compatible:

```python
class EventObserver(Protocol):
    def observe(self, event: object) -> object: ...
```

### 2.4 Related message and model values

- `Message` (`super_harness/models/types.py`, frozen): `role`, `content`, `name`, `tool_call_id`, `tool_calls` (`tuple[ToolCall, ...]`).
- `MessageRole`: `system` / `developer` / `user` / `assistant` / `tool`.
- `ModelRequest`: `messages`, `tools`, `output_schema`, `temperature`, `parallel_tool_calls`, `extra`.
- `ModelResponse`: `text`, `tool_calls`, `usage` (`Usage`), `response_id`, `finish_reason`, `output_json`.
- `ModelStreamEventType`: `started` / `text_delta` / `tool_call_delta` / `completed`.
- `ModelStreamEvent`: `type`, `delta`, `tool_call_index`, `tool_call_id`, `tool_name`, `response`.

All are frozen and stay provider-neutral across the boundary.

### 2.5 Context fragments and summaries

- `ContextKind`: `runtime` / `developer` / `project` / `persona` / `skill` / `memory` / `rag` / `summary`.
- `ContextPriority` (`IntEnum`, higher value = lower authority): `RUNTIME=10`, `DEVELOPER=20`, `PROJECT=40`, `PERSONA=50`, `SKILL=60`, `SUMMARY=70`, `MEMORY=80`, `RAG=90`.
- `ContextFragment`: `kind`, `content`, `source`, `role` (default `USER`), `priority`, `metadata`. `effective_priority` returns the explicit priority or the kind-derived default; `render()` wraps it as a user-role message `<context kind="..." source="...">…</context>`.
- `ContextSummary`: `content`, `summarized_messages`, `summary_id`, `created_at`.

## 3. Lifecycle

### 3.1 Turn lifecycle (ASCII)

A Turn's lifecycle and terminal states:

```
                     ┌────────────────────────────────────────────┐
                     │            TurnStatus state machine        │
                     └────────────────────────────────────────────┘

  start()                    model-step loop
  ┌──────────┐   ┌──────────┐   ┌──────────────┐   ┌──────────┐
  │ PENDING  │──▶│ RUNNING  │──▶│ WAITING_TOOL │──▶│ RUNNING  │ ...
  └──────────┘   └──────────┘   └──────────────┘   └──────────┘
                    │   │                              │
                    │   │  complete(response)          │  complete(response)
                    │   └──────────────▶┌──────────┐   └────────▶┌────────────┐
                    │                   │ COMPLETED │             │ (terminal)  │
                    │                   └──────────┘             └────────────┘
                    │
                    │  fail(exc)   ┌────────┐
                    └────────────▶│ FAILED │   (terminal, keeps error)
                                 └────────┘

  cancellation path:
     cancel()            ┌───────────┐
      ────────────────▶  │ CANCELLED │  (terminal, distinct from interrupt)
                         └───────────┘
  interruption path:
     interrupt() / early stream close / resumed in-flight turn
                         ┌─────────────┐
      ────────────────▶  │ INTERRUPTED │  (terminal, distinct from cancel)
                         └─────────────┘
```

`WAITING_TOOL` is a non-terminal intermediate state: it is set after tool calls arrive, returns to `RUNNING` after tool results are filled in, and continues to the next model step. It does not terminate the Turn; only `completed / failed / interrupted / cancelled` are terminal.

### 3.2 Turn execution sequence (one full streaming Turn)

```
Thread.astream(input)
  │
  ├─ Pre-guards: archived? / active_turn_id? / empty input?
  ├─ SESSION_START hook (first only), USER_PROMPT hook (may rewrite/deny input)
  ├─ create Turn(PENDING) → self._active_turn_id = turn.turn_id
  ├─ append Message(USER, input) → turn.start() → RUNNING
  ├─ TURN_START hook
  ├─ _persist()                       # snapshot persistence
  ├─ yield turn.started
  ├─ if history exceeds threshold → acompact()  (see §6)
  │
  └─ for step in 1..max_model_steps:
       ├─ drain _steering_by_turn[turn] → append <steering>…</steering> user msg, yield turn.steered
       ├─ assemble ModelRequest (developer + context fragments + summaries + history)
       ├─ BEFORE_MODEL hook
       ├─ provider.stream(request):
       │     STARTED      → yield model.started
       │     TEXT_DELTA   → yield model.text.delta
       │     TOOL_CALL_DELTA → yield model.tool_call.delta
       │     COMPLETED    → save response, yield model.completed, break
       │    exception → yield model.failed, raise (see §11)
       ├─ if no COMPLETED → RuntimeError
       ├─ AFTER_MODEL hook
       │
       ├─ if response.tool_calls and tool_executor:
       │     ├─ append Message(ASSISTANT, …, tool_calls)
       │     ├─ turn.status = WAITING_TOOL
       │     ├─ decide parallelism (registry all supports_parallel)
       │     ├─ for each call → yield tool.started
       │     ├─ execute (parallel gather or serial) → for each result:
       │     │    append Message(TOOL, …) → _persist → yield tool.completed / tool.failed
       │     ├─ turn.status = RUNNING
       │     └─ continue   # next model step
       │
       └─ otherwise (no tool calls):
             ├─ turn.complete(response) → COMPLETED
             ├─ if text or tool_calls → append Message(ASSISTANT, …)
             ├─ _persist() → TURN_END hook → yield turn.completed → break

  finally: self._active_turn_id = None
```

If the loop is exhausted without completing (`turn.status in {RUNNING, WAITING_TOOL}`), it raises `ToolError("tool loop exceeded maximum of N model steps")` and enters the failure path.

### 3.3 Terminal-path routing

`_astream_unobserved` routes three kinds of exceptions/closures to different terminal states via `try/except`:

```python
except GeneratorExit:
    turn.status = TurnStatus.INTERRUPTED      # stream consumer closed early
    turn.error = "event stream consumer closed"
    ...
    raise
except asyncio.CancelledError:
    if turn.turn_id in self._interrupt_turn_ids:
        turn.status = TurnStatus.INTERRUPTED  # explicit interrupt
        self._interrupt_turn_ids.discard(turn.turn_id)
    else:
        turn.cancel()                          # explicit cancel
    ...
    raise
except Exception as exc:
    turn.fail(exc)                             # failure: FAILED + turn.failed event
    ...
    raise
```

Key point: **cancellation and interruption are two distinct terminal states**, distinguished by whether the turn_id is registered in `_interrupt_turn_ids`.

## 4. Key interfaces / classes

### 4.1 Thread (`super_harness/runtime/thread.py`)

```python
@dataclass(slots=True)
class Thread:
    provider: ModelProvider
    instructions: str | None = None
    tool_registry: ToolRegistry | None = None
    tool_executor: ToolExecutor | None = None
    max_model_steps: int = 8
    context: ContextAssembler = field(default_factory=ContextAssembler)
    store: SQLiteThreadStore | None = None
    archived: bool = False
    parent_thread_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    summaries: list[ContextSummary] = field(default_factory=list)
    compaction_threshold_chars: int = 100_000
    compaction_retain_messages: int = 8
    hooks: HookRegistry | None = None
    observer: EventObserver | None = None
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    created_at / updated_at: datetime
    messages: list[Message]
    turns: list[Turn]
```

Key methods and signatures:

```python
async def astream(input, *, tools=(), output_schema=None) -> AsyncIterator[Event]
async def _astream_unobserved(input, *, tools=(), output_schema=None) -> AsyncGenerator[Event, None]
def start(input, *, tools=(), output_schema=None) -> TurnHandle
async def arun(input, *, tools=(), output_schema=None) -> ModelResponse
def stream(input, *, tools=(), output_schema=None) -> Iterator[Event]
def run(input, *, tools=(), output_schema=None) -> ModelResponse
def compact(summary=None, *, retain_messages=None) -> tuple[Event, Event]
async def acompact(summary=None, *, retain_messages=None) -> tuple[Event, Event]
async def aclose() -> None
def debug_context() -> ContextDebugSnapshot
def archive() -> None
def fork(*, thread_id=None) -> Thread
def queue_steering(turn_id, instruction) -> None
def request_interrupt(turn_id) -> None
@property
def active_turn_id(self) -> str | None
```

The sync guard `_sync` raises `RuntimeError("sync API cannot run inside an active event loop; use the async API")` if an event loop is already running; otherwise it collects via `asyncio.run`. This enforces the "public sync wrappers must not nest an event loop" invariant.

### 4.2 TurnHandle (`super_harness/runtime/handle.py`)

```python
class TurnHandle:
    def __init__(self, thread, input, *, tools=(), output_schema=None) -> None
    async def events(self) -> AsyncIterator[Event]
    async def wait(self) -> ModelResponse
    async def steer(self, instruction: str) -> None
    def cancel(self) -> None
    async def interrupt(self) -> None
```

Internals: `self._ready = asyncio.Event()`, `self._queue: asyncio.Queue[Event | object]`, `self._error`, and `self._task = asyncio.create_task(self._pump(...))`. `_pump` consumes `thread.astream`, puts each event on the queue, stores exceptions into `_error`, then pushes the `_DONE` sentinel and sets `_ready`.

- `events()` yields events from the queue until `_DONE`; if `_error` is set it re-raises.
- `wait()` awaits `_task` and returns that turn's `response`; if the response is missing it raises `RuntimeError(f"turn ended with status {turn.status.value}")`.
- `steer(instruction)`: awaits `_ready` (to get the turn_id) then calls `thread.queue_steering`.
- `cancel()`: calls `self._task.cancel()` directly (no interrupt registration → terminal `CANCELLED`).
- `interrupt()`: calls `thread.request_interrupt(turn_id)` first, then `self._task.cancel()` (registers interrupt → terminal `INTERRUPTED`).

### 4.3 Agent (`super_harness/agent.py`) — Thread factory

```python
class Agent:
    def __init__(self, provider, *, instructions=None, tools=(), approval=None,
                 hooks=None, observer=None, max_model_steps=8, context=(),
                 cwd=None, agents_loader=None, store=None,
                 compaction_threshold_chars=100_000, persona=None)
    def thread(self) -> Thread
    def resume(self, thread_id) -> Thread
    def fork(self, thread_id) -> Thread
    async def arun(...) -> ModelResponse
    def run(...) -> ModelResponse
    def astream(...) -> AsyncIterator[Event]
    def stream(...) -> Iterator[Event]
    async def aclose(self) -> None
```

`Agent.thread()` builds an independent `Thread` from the current provider/tool/hook configuration and immediately `save`s a snapshot if a `store` is configured. `Agent.resume(thread_id)` loads the snapshot and marks every `pending/running/waiting_tool` Turn as `INTERRUPTED` (`error = "interrupted before resume"`), never silently restoring an in-flight Turn as completed.

### 4.4 Context assembly (`super_harness/context/fragments.py`)

```python
class ContextAssembler:
    max_chars: int = 100_000
    fragments: list[ContextFragment]
    def add(self, fragment) -> None
    def extend(self, fragments) -> None
    def ordered(self) -> tuple[ContextFragment, ...]   # dedupe → sort by authority → budget truncate
    def messages(self) -> tuple[Message, ...]          # render as <context> user messages

def redact_text(value: str) -> str
```

### 4.5 AGENTS.md resolver (`super_harness/context/agents_md.py`)

```python
@dataclass(frozen=True, slots=True)
class AgentsMdLoader:
    root_markers: tuple[str, ...] = (".git",)
    max_bytes: int = 32_768
    filenames: tuple[str, ...] = ("AGENTS.override.md", "AGENTS.md")
    def project_root(self, cwd: Path) -> Path
    def discover(self, cwd) -> tuple[Path, ...]
    def load(self, cwd) -> tuple[ContextFragment, ...]  # ContextKind.PROJECT, role USER
```

## 5. Concurrency / cancellation

### 5.1 Single active Turn constraint

`Thread._active_turn_id` is a single-active guard: `_astream_unobserved` checks it up front and raises `RuntimeError("thread already has an active turn")` if a Turn is already active. So **only one active Turn per Thread at a time**; history accumulates via the ordered `turns` list.

### 5.2 Streaming is the authoritative path; cancellation propagates down

Streaming is authoritative. `arun`/`run` are thin consumers of `astream`/`stream`: they collect events and only take the `response` back when they see `turn.completed`, otherwise raising `RuntimeError("turn ended without a response")`.

Cancellation propagates through the async generator to the provider (and onward to HTTPX): `_astream_unobserved` re-raises `asyncio.CancelledError` from the `async for model_event in self.provider.stream(request)` loop (see §3.3), and `finally` guarantees `_active_turn_id` is cleared. The provider layer closes the active HTTP stream (per `docs/research/codex/model-provider-and-streaming.md`: dropping/cancelling a stream cancels downstream work).

### 5.3 Steering is injected only at safe checkpoints

`queue_steering(turn_id, instruction)` appends the instruction to `_steering_by_turn[turn_id]` and does **not** inject it immediately. The real injection happens at the next model-step checkpoint: at the start of each step, `for instruction in self._steering_by_turn.pop(turn.turn_id, [])` wraps the instruction as a `<steering>{instruction}</steering>` user message appended to history and `yield turn.steered`. Steering never interrupts an in-flight model call; it only takes effect safely at a model-step boundary.

### 5.4 Parallel tool execution

When one response contains multiple tool calls and every registered tool `supports_parallel`, they run concurrently with `asyncio.gather`:

```python
if parallel:
    results = await asyncio.gather(
        *(self.tool_executor.execute(call) for call in response.tool_calls)
    )
else:
    results = []
    for call in response.tool_calls:
        results.append(await self.tool_executor.execute(call))
```

Tool results are zipped back into `Message(TOOL, …)` in call order for stable ordering. Cancellation propagates to the parallel tasks (gathering cancels the sibling tasks when one is cancelled).

### 5.5 Controlling an active Turn (TurnHandle)

`start()` returns a `TurnHandle` whose `_pump` runs as an `asyncio.create_task`, pumping the same authoritative Thread event stream in the background. Therefore:

- The caller can `steer` / `interrupt` / `cancel` the active Turn without blocking stream consumption.
- `_ready` is set when the first event carrying a `turn_id` arrives, so `steer`/`interrupt` never misreport "turn is no longer active" before the turn_id is known.
- The `_task.done()` check prevents steering into an already-finished Turn.

## 6. Persistence

`SQLiteThreadStore` (`super_harness/persistence/sqlite.py`) stores transactional full snapshots in versioned SQLite tables (`SCHEMA_VERSION = 1`):

- `threads` table: `thread_id` (PK), `created_at`, `updated_at`, `instructions`, `archived`, `parent_thread_id`, `metadata_json`, `summaries_json`.
- `messages` table: `(thread_id, position)` PK with `data_json`.
- `turns` table: `(thread_id, position)` PK with `data_json`.

Key points:

- **Transactional**: `save` runs inside `with self._lock, self._connection:`, upserting `threads`, then `DELETE`ing old messages/turns, then bulk-inserting — any failure rolls back the whole batch, never leaving a half-written state.
- **Provider-neutral**: it serializes neutral messages, tool calls, usage, structured output, summary IDs, timestamps, archive state, and fork lineage — no Responses API items, rollout JSONL wire objects, OpenAI IDs, or account metadata.
- **WAL + foreign_keys**, with `check_same_thread=False` plus a `threading.RLock` for cross-thread safety.
- `load` returns a `ThreadSnapshot` (`thread_id/created_at/updated_at/instructions/archived/parent_thread_id/metadata/messages/turns/summaries`).
- `archive(thread_id, archived=True)` is a metadata operation that does not delete history; `ids()` lists non-archived Threads.

`Thread._persist()` fires at key points: after a turn starts, after each tool result is written back, after a turn completes, after a terminal state settles, and after compaction. `fork()` derives a new ID from an explicit snapshot boundary (`parent_thread_id = self.thread_id`) and persists.

Resume semantics (`Agent.resume`): the original ID and history are restored; **in-flight Turns (pending/running/waiting_tool) are marked `INTERRUPTED`, never silently completed** — an unfinished model call cannot be reconstructed from a snapshot.

## 7. Events / observability

### 7.1 Event types emitted by Thread (stable dotted names)

| Event type | Correlation | Key payload fields |
|---|---|---|
| `turn.started` | turn | — |
| `turn.steered` | turn | `instruction` |
| `turn.completed` | turn | `response` |
| `turn.failed` | turn | `error_type`, `message` |
| `model.started` | turn | `provider`, `model`, `step` |
| `model.text.delta` | turn | `delta`, `step` |
| `model.tool_call.delta` | turn, tool_call | `index`, `name`, `delta`, `step` |
| `model.completed` | turn | `response`, `usage`, `tool_calls`, `provider`, `model`, `step` |
| `model.failed` | turn | `provider`, `model`, `step`, `error_class`, `message` |
| `tool.started` | turn, tool_call | `name`, `arguments` |
| `tool.completed` | turn, tool_call | `result`, `success` |
| `tool.failed` | turn, tool_call | `result`, `success` |
| `compaction.started` | thread | `before_messages`, `summarized_messages` |
| `compaction.completed` | thread | `after_messages`, `summary_id` |

Every event carries an `event_id` (uuid4) and a UTC `timestamp`, and fills `thread_id` / `turn_id` / `tool_call_id` where applicable, forming a thread→turn→model/tool correlation chain. Payloads are always read-only.

### 7.2 Observer

`Thread.astream` calls `observer.observe(event)` on every event (when configured) and accepts both sync and async return values:

```python
async for event in operation:
    if self.observer is not None:
        outcome = self.observer.observe(event)
        if inspect.isawaitable(outcome):
            await cast(Awaitable[object], outcome)
    yield event
```

The observation path is downstream of immutable lifecycle events and never controls scheduling or provider responses (see `docs/research/codex/observability-and-hardening.md`).

### 7.3 Context debug snapshot

`Thread.debug_context()` returns `ContextDebugSnapshot(thread_id, entries, history_messages, estimated_characters)`. Each `ContextDebugEntry` holds `kind/source/role/priority/content`, where `content` has already passed through `redact_text` (masking `api_key`/`token`/`secret`/`password` assignments and `sk-…`-shaped tokens). This makes the "debug context" a first-class public value rather than an app-server-only diagnostic surface.

### 7.4 Hook events

The runtime dispatches Hooks (`HookEvent`) at several lifecycle points: `SESSION_START`/`SESSION_END`, `TURN_START`/`TURN_END`, `USER_PROMPT`, `BEFORE_MODEL`/`AFTER_MODEL`, `PRE_COMPACT`/`POST_COMPACT`, `ERROR`. Hooks may rewrite inputs (e.g. `USER_PROMPT` rewrites `input`, `BEFORE_MODEL` rewrites `request`, `PRE_COMPACT` rewrites `summary`/`retain_messages`) or `deny` them (raising `HookError`). Failed hooks receive the original exception.

## 8. Codex reference

This project pins and reviews Codex's (Rust) equivalent implementation; the evidence is recorded in:

- `docs/research/codex/agent-runtime-thread-turn.md` — Thread/Turn lifecycle, events, cancellation/interruption behavioral contract and invariants.
- `docs/research/codex/durable-thread-context-compaction.md` — persistence, context fragments, AGENTS.md resolution, and compaction contracts and invariants.
- `docs/research/codex/model-provider-and-streaming.md` — the authoritative streaming path, retryable early closure, and cancellation propagation to HTTPX.

Mirrored sources live under `references/codex/`; the key inspected files include:

- `codex-rs/core/src/session/turn.rs`, `codex-rs/core/src/codex_thread.rs`, `codex-rs/core/src/thread_manager.rs`
- `codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs`, `.../v2/turn.rs`
- `codex-rs/thread-store/src/lib.rs`, `.../in_memory.rs`, `.../live_thread.rs`, `.../types.rs`
- `codex-rs/context-fragments/src/fragment.rs`, `.../additional_context.rs`
- `codex-rs/core/src/agents_md.rs`, `codex-rs/core/src/context_manager/history.rs`, `.../normalize.rs`, `codex-rs/core/src/compact.rs`

The behavioral contract distilled from Codex (reproduced point-by-point here):

- A Thread owns ordered history and Turns; a Turn owns one user-initiated execution with explicit lifecycle states, timestamps, and error records.
- The runtime appends user input, invokes the model, records assistant output, and continues only when normalized calls require another orchestration step.
- Events carry correlation identifiers and expose lifecycle without requiring clients to inspect internal state.
- Cancellation and interruption are observable terminal outcomes; failed/cancelled Turns retain diagnostic state.
- Context fragments retain role, classification, provenance, and marker identity instead of becoming untraceable string concatenation.
- AGENTS instructions are discovered from project root to cwd, never above the root, with local override precedence and a total byte budget.
- Compaction preserves a summary plus the recent suffix and records an explicit boundary/event.

## 9. Python-native redesign

Mapping from Codex's Rust implementation to Python:

| Rust (Codex) | Python (Super Harness) |
|---|---|
| `turn.rs` state machine | `TurnStatus` (StrEnum) + `Turn` dataclass method guards |
| `codex_thread.rs` | `Thread` dataclass + `_astream_unobserved` generator |
| `thread_manager.rs` | `Agent` (Thread factory) + `SQLiteThreadStore` |
| app-server protocol v2 thread/turn | immutable `Event` (generic event envelope) |
| `context-fragments` | `ContextFragment` + `ContextAssembler` (authority/dedupe/budget/provenance) |
| `agents_md.rs` | `AgentsMdLoader` (`.git` root discovery + override precedence + byte cap) |
| `compact.rs` | `compact`/`acompact` + `extractive_summary` + `ContextSummary` |
| client streaming | `ModelProvider.stream` → `AsyncIterator[ModelStreamEvent]` |

Python-native design decisions:

- The streaming API (`astream`) is authoritative; `arun`/`run` are thin consumers.
- Events use stable dotted names plus the generic immutable envelope (`Event`), consistent with Phase 0.
- The default compactor is deterministic and extractive (`extractive_summary`) and makes no extra provider call; applications may supply a higher-quality summary explicitly.
- Debug snapshots (`debug_context`) are first-class public values since Phase 3.

## 10. Intentional differences

- **Storage shape**: Codex pairs JSONL plus SQLite metadata; this project uses SQLite as the single authoritative store in V1, with transactional full snapshots.
- **Default compactor**: Codex's compaction may rely on the model; here the default is a deterministic extractive summary (preserving security/permission keyword lines), with higher-quality summaries injected explicitly by the application to avoid a forced extra model call.
- **Single active Turn constraint**: this project currently enforces "one active Turn per Thread at a time" via the `_active_turn_id` guard in in-memory runs; this is close to Codex reusing a turn-scoped provider session but constrains concurrent entry more strictly.
- **Explicit `WAITING_TOOL` state**: the tool-waiting phase is modeled as a distinct non-terminal state separate from `RUNNING`, making the tool stage's observability and resume semantics clearer.
- **Cancellation vs. interruption split**: `cancel()` and `interrupt()` yield two different terminal states rather than merging both into one "stop".

## 11. Failure model

### 11.1 Exception types and mapping

| Condition | Exception | Turn terminal state |
|---|---|---|
| Running an archived Thread | `RuntimeError("cannot run an archived thread")` | — (no Turn created) |
| Thread already has an active Turn | `RuntimeError("thread already has an active turn")` | — |
| Empty input | `ValueError("turn input must be non-empty")` | — |
| User prompt denied by a hook | `HookError` | failure path |
| Tool loop over budget | `ToolError("tool loop exceeded maximum of N model steps")` | FAILED |
| Provider stream without COMPLETED | `RuntimeError("provider completed without a normalized response")` / `"...ended without a completed event"` | FAILED |
| Provider raises | original exception (after `model.failed`) | FAILED |
| `cancel()` | `asyncio.CancelledError` | CANCELLED |
| `interrupt()` | `asyncio.CancelledError` + registration | INTERRUPTED |
| Stream consumer closes early | `GeneratorExit` | INTERRUPTED |
| In-flight Turn before resume | — (marked by `resume` directly) | INTERRUPTED |
| Sync API inside an event loop | `RuntimeError("sync API cannot run inside an active event loop")` | — |

Every exception path first `_persist()`s (writing the terminal state), then (if configured) dispatches the `ERROR` hook, then `yield turn.failed` and re-raises. Failure is thus both an event and an exception downstream, with diagnostics preserved in both.

### 11.2 Early stream closure (retryable protocol failure)

A provider stream succeeds only after `COMPLETED`; early closure is a retryable protocol failure within the configured stream budget (retried by the provider layer, per `model-provider-and-streaming.md`). On the Thread side, a stream that ends without `completed` is always treated as an error — partial results are never silently accepted.

### 11.3 Retry / timeout ownership

- Model retries and stream timeouts are owned by the provider layer (bounded retry budget; auth/invalid requests are not retried).
- The Thread does not retry: one failure immediately enters the FAILED terminal state and re-raises.
- Tool execution has its own time-bound/approval path (`ToolExecutor`); its denial and validation failures return as failed `ToolResult` **data** so the model can recover, while task cancellation remains an exception.

## 12. Extension points

- **Provider**: implement the `ModelProvider` protocol (`stream`/`complete`/`aclose` + `name`/`capabilities`) to plug in any model backend, with zero coupling to provider SDKs.
- **Observer**: implement `EventObserver.observe` to attach any observability backend; the event stream is a read-only downstream view.
- **Hooks**: `HookRegistry` registers `(priority, source, name)` handlers that can rewrite input/request/compaction parameters at points such as `USER_PROMPT`/`BEFORE_MODEL`/`PRE_COMPACT`, or `deny` them.
- **Context fragments**: inject any `ContextKind`'s `ContextFragment` (e.g. MEMORY, RAG, PERSONA, SKILL) via `Agent(context=[...])`, participating in authority sorting and budgeting.
- **AGENTS loading**: pass a custom `AgentsMdLoader` to replace root markers, filenames, and the byte cap.
- **Compaction summaries**: `acompact(summary=...)` or the `PRE_COMPACT` hook can inject application-level summaries instead of the default extractive one.
- **Persistence**: the `store` parameter accepts any store implementing `save`/`load`/`archive`/`ids`; V1 is `SQLiteThreadStore`.

## 13. Tests

Corresponding test files (`tests/`):

- `tests/test_agent_runtime.py` — basic async/sync runs append user/assistant history; repeated runs reuse history but create distinct ordered Turns; streaming emits turn/model lifecycle plus text deltas in order; provider failure marks FAILED and emits a single `turn.failed` terminal event; cancellation marks CANCELLED and preserves history; sync methods reject use from an already-running event loop.
- `tests/test_context_and_persistence.py` — context precedence, deduplication, budget, provenance, and redaction; AGENTS.md root/nested order, override precedence, byte limit, and no walk above root; create/save/reopen/resume with stable IDs, fork isolation and lineage, archive blocking new runs without deleting history; transaction rollback and schema version.
- `tests/test_events.py`, `tests/test_model_types.py` — event envelope validation and immutable/validated model values.
- `tests/test_examples.py` — regression runs over the 91 `examples/` examples (covering `02_streaming`, `07_durable_thread`, `08_agents_context_debug`, `09_compaction_and_control`, and more).
- `tests/test_hooks.py`, `tests/test_tools.py` — hook dispatch and tool execution/approval/cancellation propagation.

Example verification chain (runnable; see §"Links"):
- `examples/02_streaming/main.py` — consumes correlated runtime events (`model.text.delta`).
- `examples/07_durable_thread/main.py` — persist/reopen/resume/fork.
- `examples/08_agents_context_debug/main.py` — hierarchical AGENTS.md discovery + redacted context.
- `examples/09_compaction_and_control/main.py` — compaction + interrupting an active TurnHandle.
- `examples/84_compaction_custom_summary.py`, `examples/85_compaction_retention.py` — custom summary / retained suffix.
- `examples/47_agent_budget_cancel.py` — multi-agent budget and interrupt (cross-chapter reference).

## 14. Limitations / future work

- **Single active Turn**: only one active Turn per Thread at a time; multi-Turn concurrency needs an explicit concurrency policy and per-session isolation.
- **Compaction quality**: the default extractive summary may lose detail; generating summaries with the provider is the better path (currently supported via explicit `acompact(summary=...)`, but there is no built-in "model compaction" call path yet).
- **In-memory run**: Phase 1/2 `Thread` runs in memory; the full persist/resume path depends on `SQLiteThreadStore`, and cross-process state recovery continues to evolve with the persistence expansion.
- **Stream-interrupt retry**: early stream closure retries are entirely delegated to the provider; the Thread has no cross-model-step auto-continuation, so one failure is terminal.
- **Context budget granularity**: the budget truncates at fragment boundaries by total characters; there is no token budget or authority-weighted budget yet.
- **AGENTS caching**: AGENTS files are re-parsed on every Agent construction; there is no caching/invalidation policy yet.
- **Steering checkpoint granularity**: steering can only be injected at model-step boundaries; finer checkpoints (between tool calls) may come later.
- **Archive semantics**: `archive` blocks new runs but keeps history; there is no lifecycle deletion/retention policy yet.

## Links

- Runnable examples: `examples/02_streaming`, `examples/07_durable_thread`, `examples/08_agents_context_debug`, `examples/09_compaction_and_control`, `examples/84_compaction_custom_summary`, `examples/85_compaction_retention`
- [View the complete runnable example 02_streaming](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)
- [View the complete runnable example 07_durable_thread](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py)
- [View the complete runnable example 08_agents_context_debug](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)
- [View the complete runnable example 09_compaction_and_control](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)
- [View the complete runnable example 84_compaction_custom_summary](https://github.com/Sitozzmonash/superharness/blob/main/examples/84_compaction_custom_summary.py)
- [View the complete runnable example 85_compaction_retention](https://github.com/Sitozzmonash/superharness/blob/main/examples/85_compaction_retention.py)
- Research docs: `docs/research/codex/agent-runtime-thread-turn.md`, `docs/research/codex/durable-thread-context-compaction.md`, `docs/research/codex/model-provider-and-streaming.md`
- API reference: `website/docs/api-reference.md`
