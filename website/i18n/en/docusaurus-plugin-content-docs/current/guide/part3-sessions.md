---
id: guide-part3-sessions
title: "User Guide · Part III: Sessions"
sidebar_position: 3
description: Thread basics, multi-turn, durable SQLite threads, streaming events, interrupt/steer/cancel, compaction, and AGENTS.md discovery.
---

# Part III: Sessions (Threads)

This part explains how to organize all of the state of a session: from the simplest single Q&A, to durable multi-turn conversations that survive process restarts, to observing, interrupting, steering, cancelling, and compacting an actively running turn. Everything is based on the real implementation in `src/super_harness`, and the sample code can be run directly from the `examples/` directory.

## 1. What this is / When to use it

In Super Harness, a **Thread** is the full state container for one session: it holds the ordered conversation history (`messages`), the execution record for each turn (`turns`), the summaries produced by compaction (`summaries`), context fragments, metadata, and the provider and tool configuration it belongs to.

A **Turn** is one user input and its complete execution inside a Thread: a single input goes through model calls, possibly a tool-call loop, and finally reaches a terminal state (completed / failed / interrupted / cancelled). A Thread only allows one active Turn at a time (concurrent activation is rejected).

**When to use it:**

- One-shot Q&A only → use `Agent.run(...)` / `Agent.arun(...)` directly; they create a fresh Thread internally.
- Multi-turn context (later turns must remember earlier ones) → reuse one Thread: `thread = agent.thread()` and call `thread.run(...)` repeatedly.
- Preserve sessions across processes / restarts → configure a `SQLiteThreadStore` and restore with `agent.resume(thread_id)`.
- Open an independent branch of a session without polluting the original → `agent.fork(thread_id)` or `thread.fork()`.
- Watch text live while the model is generating, or intervene at a safety checkpoint → use streaming events and `TurnHandle` (`astream`, `steer`, `interrupt`, `cancel`).
- Control growth of the context window → compact manually or automatically.
- Let the model understand project rules → `AGENTS.md` discovery via `cwd`, or inject explicitly with `ContextFragment`.

## 2. Prerequisites

- Install: run `pip install -e .` from the repository root.
- For a real model, set the `DEEPSEEK_API_KEY` environment variable (the default China-ready provider is `DeepSeekProvider`).
- Most examples use a custom local `Provider` (e.g. `LocalProvider` / `BlockingProvider` / `OfflineProvider` in the examples); they need no network and run directly.
- The async API requires a running event loop; do not call synchronous methods from an active event loop (they raise `RuntimeError`).
- Before using persistence, decide on the SQLite database file path (e.g. `threads.db`).

## 3. Quick start

A minimal multi-turn session:

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider(), instructions="Answer concisely.")
thread = agent.thread()

first = thread.run("What is 2 + 2?")
second = thread.run("Now double the previous answer.")
print(first.text)
print(second.text)
```

Key points:

- `agent.thread()` returns a new, independent `Thread`; repeated `run` calls on the same Thread automatically carry prior history.
- `Agent.run(...)` is shorthand for `agent.thread().run(...)`, starting from scratch each time, with no retained history.
- When done, `await agent.aclose()` (async) or let the process exit normally (sync).

## 4. Configuration

### 4.1 Environment variables

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | Request-time credential for `DeepSeekProvider` | none (errors if unset) |

Credentials are read from the variable at request time and are **never** written into events or persisted data.

### 4.2 Agent constructor parameters (Thread-related)

```python
agent = Agent(
    provider,
    *,
    instructions=None,               # developer instructions, prepended as a DEVELOPER message
    max_model_steps=8,               # max model steps per turn (tool-loop ceiling)
    context=(),                      # initial list of ContextFragment
    cwd=None,                        # search upward from this dir for AGENTS.md project rules
    agents_loader=None,              # custom AGENTS.md loader (default AgentsMdLoader)
    store=None,                      # SQLiteThreadStore, enables persistence
    compaction_threshold_chars=100_000,  # auto-compaction threshold (chars)
    persona=None,                    # persona; see the persona section
)
```

### 4.3 Thread-related attributes

The created `Thread` exposes these readable/writable fields: `thread_id`, `parent_thread_id`, `messages`, `turns`, `summaries`, `metadata`, `archived`, `created_at`, `updated_at`, `max_model_steps`, `compaction_threshold_chars`, `compaction_retain_messages`, plus the read-only `active_turn_id`.

`compaction_retain_messages` defaults to `8` and controls how many recent messages are kept when compacting.

## 5. Thread basics & multi-turn

### 5.1 What this is

A `Thread` is a reusable conversation context. As long as you call `run`/`arun` on the **same** Thread, history accumulates; calling `Agent.run` creates a new one each time.

### 5.2 Basic example

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider(), instructions="Answer concisely.")
thread = agent.thread()

thread.run("My name is Ada.")
thread.run("I work on the release tooling.")
reply = thread.run("What do you know about me?")
print(reply.text)  # references the context from the previous two turns
```

### 5.3 Real-world example

A multi-turn support or diagnostic conversation that accumulates user preferences into one session:

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider(), instructions="Be brief and helpful.")
    thread = agent.thread()

    thread.run("Preferred deployment: Render, region us-east.")
    thread.run("Budget under $50/month.")
    reply = thread.run("Which plan fits my requirements?")
    print(reply.text)

    await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

### 5.4 Advanced example

Mix structured output (`output_schema`) with tools on the same Thread so each step can see the previous step's result:

```python
import asyncio
from super_harness import Agent, DeepSeekProvider, tool

@tool
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right

SCHEMA = {
    "type": "object",
    "properties": {"total": {"type": "integer"}},
    "required": ["total"],
}

async def main() -> None:
    agent = Agent(DeepSeekProvider(), tools=[add], instructions="Use the add tool.")
    thread = agent.thread()
    response = await thread.arun("add 20 and 22", output_schema=SCHEMA)
    print(response.output_json)  # normalized structured result
    await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

`output_schema` makes the model return structured output per the JSON Schema; `thread.messages` keeps the full conversation history for later turns.

## 6. Durable SQLite threads

### 6.1 What this is / When to use it

`SQLiteThreadStore(path)` writes a full snapshot of a Thread (messages, turns, summaries, metadata, parent/child relationships, archive flag) into SQLite, using WAL mode and transactions. Use it to:

- Restore a session after a process restart (`agent.resume(thread_id)`).
- Branch off a session without affecting the original (`agent.fork(thread_id)`).
- Keep history but block new turns (`thread.archive()`).
- List all threads via `store.ids()`.

As soon as you pass a `store` to `Agent`, `agent.thread()` persists **immediately**.

### 6.2 Basic example

```python
from super_harness import Agent, SQLiteThreadStore

with SQLiteThreadStore("threads.db") as store:
    agent = Agent(provider, store=store)
    thread = agent.thread()
    thread.run("remember this")
    print(thread.thread_id)          # stable UUID, usable to resume after restart
    print(store.ids())               # list all non-archived threads
```

### 6.3 Real-world example

Full lifecycle across process restarts: write, close, reopen, resume, and fork.

```python
import asyncio
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from super_harness import Agent, SQLiteThreadStore
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)

class LocalProvider:
    name = "local"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("saved")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("saved"))

    async def aclose(self) -> None:
        return None

async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "threads.db"
        with SQLiteThreadStore(database) as store:
            agent = Agent(LocalProvider(), store=store)
            thread = agent.thread()
            await thread.arun("remember this")
            thread_id = thread.thread_id

        # Simulate a process restart: reopen with the same database file
        with SQLiteThreadStore(database) as store:
            agent = Agent(LocalProvider(), store=store)
            resumed = agent.resume(thread_id)
            forked = resumed.fork()
            print(resumed.thread_id, resumed.messages[-1].content)
            print("fork", forked.thread_id, "parent", forked.parent_thread_id)

if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py)

### 6.4 Advanced example

Continue a conversation after `resume`, and use `agent.fork(thread_id)` (equivalent to `resume` + `fork`) to open an independent branch from a historical session, combined with `store.ids()` to manage multiple sessions:

```python
from super_harness import Agent, SQLiteThreadStore

with SQLiteThreadStore("threads.db") as store:
    agent = Agent(provider, store=store)

    # List historical sessions and continue one of them
    for thread_id in store.ids():
        continued = agent.resume(thread_id)
        continued.run("continue from where we left off")

    # Fork directly from a session, producing a child with parent_thread_id
    branch = agent.fork(thread_id)
    print(branch.parent_thread_id)  # points at the forked parent thread
```

**About archiving**: `thread.archive()` sets `archived` to `True` and persists it. After archiving, any `run`/`arun`/`astream` raises `RuntimeError("cannot run an archived thread")`, but the history is still readable via `store.load(thread_id)`; `store.ids(include_archived=True)` lists archived threads, and `store.archive(thread_id, archived=False)` un-archives one.

## 7. Streaming & events

### 7.1 What this is

The runtime is async-native. `astream` yields **immutable** `Event` objects (`@dataclass(frozen=True)`) one at a time, for live rendering and correlation. Text arrives as `model.text.delta`, followed by `model.completed` and `turn.completed`. `arun` simply consumes the whole stream and returns the final normalized `ModelResponse`.

### 7.2 Basic example

```python
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

### 7.3 Real-world example

Stream text deltas live in a CLI/chat UI and record usage:

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        usage = None
        async for event in agent.astream("Explain concurrency in one paragraph."):
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
            elif event.type == "model.completed":
                usage = event.payload.get("usage")
        print()
        print("usage:", usage)
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.4 Advanced example

Use `thread.start(input)` to get a `TurnHandle`, and consume the full set of events (including tool lifecycle) in the background via `handle.events()` to trace the model and tool steps of a turn:

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        thread = agent.thread()
        handle = thread.start("Summarize the event model briefly.")
        async for event in handle.events():
            print(event.type, dict(event.payload) if event.payload else "")
        response = await handle.wait()
        print("done:", response.text[:80])
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

### 7.5 Event types at a glance

| Event type | When it fires | Key payload |
| --- | --- | --- |
| `turn.started` | a turn begins | `thread_id`, `turn_id` |
| `model.started` | a model call begins | `provider`, `model`, `step` |
| `model.text.delta` | text delta | `delta`, `step` |
| `model.tool_call.delta` | streaming tool-argument delta | `index`, `name`, `delta` |
| `model.completed` | model finishes one response | `response`, `usage`, `tool_calls`, `step` |
| `model.failed` | model call raised | `error_class`, `message`, `step` |
| `tool.started` | tool begins executing | `name`, `arguments` |
| `tool.completed` / `tool.failed` | tool finishes | `result`, `success` |
| `turn.steered` | received a steer instruction | `instruction` |
| `turn.completed` | a turn completes normally | `response` |
| `turn.failed` | a turn fails | `error_type`, `message` |
| `compaction.started` / `compaction.completed` | around compaction | see the compaction section |

## 8. Interrupt, steer & cancel

### 8.1 What this is / When to use it

`TurnHandle` is a handle to an active Turn and offers three kinds of control:

- `await handle.steer(instruction)`: **steer** a running turn at a safety checkpoint (appends a `<steering>` instruction) without terminating it.
- `await handle.interrupt()`: request an interrupt of the current turn, recording the `INTERRUPTED` terminal state.
- `handle.cancel()`: hard-cancel the underlying task, recording the `CANCELLED` terminal state.

Both `steer` and `interrupt` wait for the turn to actually start (internally waiting on readiness) and validate that `turn_id` is still valid.

### 8.2 Basic example

```python
import asyncio
from super_harness import Agent

async def main() -> None:
    thread = Agent(provider).thread()
    handle = thread.start("long operation")
    iterator = handle.events().__aiter__()
    print((await anext(iterator)).type)  # turn.started
    await handle.interrupt()
    try:
        async for event in iterator:
            print(event.type)
    except asyncio.CancelledError:
        print("turn interrupted")

if __name__ == "__main__":
    asyncio.run(main())
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)

### 8.3 Real-world example

Run a task that may take a long time while showing progress live; if the user hits "stop", interrupt it; if a new instruction arrives at a safety checkpoint, steer the model to adjust direction:

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        thread = agent.thread()
        handle = thread.start("Draft a long release plan.")
        async for event in handle.events():
            if event.type == "model.text.delta":
                print(event.payload["delta"], end="", flush=True)
            # Safety checkpoint: steer the model to add a testing section
            if event.type == "turn.started":
                await handle.steer("After drafting, always add a testing section.")
        response = await handle.wait()
        print("\nfinal:", response.text[:60])
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

> Note: `steer` appends a `<steering>` user message and emits a `turn.steered` event afterwards; it is suited to adjusting direction before the model starts generating, not to rewriting text already emitted.

### 8.4 Advanced example

Timeout control: set an external deadline for a turn, `cancel()` when it expires, and print the resulting terminal state:

```python
import asyncio
from super_harness import Agent, DeepSeekProvider

async def main() -> None:
    agent = Agent(DeepSeekProvider())
    try:
        thread = agent.thread()
        handle = thread.start("Write a very long analysis.")
        try:
            await asyncio.wait_for(handle.wait(), timeout=30)
        except asyncio.TimeoutError:
            handle.cancel()
            print("cancelled after timeout")
        # Inspect the terminal state recorded on the Thread
        for turn in thread.turns:
            print(turn.status.value)
    finally:
        await agent.aclose()

if __name__ == "__main__":
    asyncio.run(main())
```

**Concurrency constraint**: a Thread only allows one active Turn at a time. If a turn is already active, another `run`/`start`/`astream` raises `RuntimeError("thread already has an active turn")`. So after starting background execution, either consume `handle.events()` or `await handle.wait()` before starting the next turn.

## 9. Compaction

### 9.1 What this is / When to use it

Long sessions accumulate lots of history and approach the context window. `thread.compact(summary=None, *, retain_messages=None)` replaces an old history prefix with a **summary**, keeping the most recent messages.

- The default `extractive_summary` is a deterministic extractive summarizer (no extra model request) and **deliberately keeps** lines mentioning `permission` / `approval` / `sandbox` / `secret` / `credential` / `denied`, so security and permission state is not lost.
- You can also pass your own `summary` string.
- `retain_messages` overrides `compaction_retain_messages` (default `8`).
- Automatic compaction: when `_history_characters()` (the sum of all message content lengths) exceeds `compaction_threshold_chars`, a new turn compacts automatically before it starts.
- `compact` returns `(Event, Event)`: `compaction.started` and `compaction.completed`.

### 9.2 Basic example

```python
from super_harness import Agent

thread = Agent(provider).thread()
# inject 12 old messages
thread.messages.extend(...)          # see the full example
for event in thread.compact(retain_messages=3):
    print(event.type, dict(event.payload))
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)

### 9.3 Real-world example

Replace the old prefix with an application-provided summary, keeping only the newest 1 message:

```python
from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)

class OfflineProvider:
    name = "offline"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass

thread = Agent(OfflineProvider()).thread()
thread.messages.extend(
    (
        Message(MessageRole.USER, "Remember release policy"),
        Message(MessageRole.ASSISTANT, "Recorded"),
    )
)
print([event.type for event in thread.compact("Release policy was recorded.", retain_messages=1)])
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/84_compaction_custom_summary.py)

### 9.4 Advanced example

Inspect retention behavior: keep the newest `retain_messages`, summarize the rest, and read the metadata in `thread.summaries`:

```python
from collections.abc import AsyncIterator

from super_harness import Agent
from super_harness.models import Message, MessageRole, ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent

class OfflineProvider:
    name = "offline"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse()

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if False:
            yield ModelStreamEvent("started")

    async def aclose(self) -> None:
        pass

thread = Agent(OfflineProvider()).thread()
thread.messages.extend(Message(MessageRole.USER, f"message {index}") for index in range(8))
thread.compact(retain_messages=2)
print(thread.summaries[-1].summarized_messages, len(thread.messages))
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/85_compaction_retention.py)

**Automatic compaction config**:

```python
from super_harness import Agent

agent = Agent(
    provider,
    compaction_threshold_chars=50_000,   # auto-compact when history exceeds 50k chars
)
```

**Constraints**: `retain_messages` must be at least `1`, otherwise a `ValueError` is raised. The compacted prefix comes from `messages[:count]`, where `count = max(len(messages) - retain, 0)`; if `count == 0`, only the `compaction.started`/`compaction.completed` events are emitted without changing history. Each compaction accumulates the `summarized_messages` count into a `ContextSummary`.

## 10. Context fragments & AGENTS.md discovery

### 10.1 What this is / When to use it

`ContextFragment` is a typed context unit carrying **kind, source, role, priority, and metadata**. Multiple fragments are sorted, deduplicated, and bounded by a total character limit by `ContextAssembler`, then injected into every request.

`AGENTS.md` discovery is a convenient mechanism for injecting project rules: pass `cwd` to `Agent`, and the runtime walks from the nearest `.git` root down to `cwd`, looking for `AGENTS.override.md` or `AGENTS.md` in each directory (override wins within a directory), and **never walks upward past `cwd`**. The default total cap is 32 KiB.

### 10.2 Basic example

```python
from super_harness import Agent, ContextFragment, ContextKind

agent = Agent(
    provider,
    context=[
        ContextFragment(ContextKind.PROJECT, "Release cadence is monthly.", "docs/releases"),
        ContextFragment(ContextKind.RAG, "Team prefers Python.", "knowledge/team"),
    ],
)
thread = agent.thread()
print([e.priority for e in thread.debug_context().entries])
```

`ContextKind` values: `RUNTIME`, `DEVELOPER`, `PROJECT`, `PERSONA`, `SKILL`, `MEMORY`, `RAG`, `SUMMARY`. Priority defaults by kind (`ContextPriority`), and can be overridden with an explicit `priority=`.

### 10.3 Real-world example

Hierarchical `AGENTS.md` discovery plus inspection of a redacted context snapshot:

```python
import tempfile
from pathlib import Path

from super_harness import Agent, DeepSeekProvider

def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / ".git").mkdir()
        nested = root / "src"
        nested.mkdir()
        (root / "AGENTS.md").write_text("Root rule", encoding="utf-8")
        (nested / "AGENTS.override.md").write_text(
            "Nested rule; api_" + "key=example-sensitive-value", encoding="utf-8"
        )
        thread = Agent(DeepSeekProvider(), cwd=str(nested)).thread()
        for entry in thread.debug_context().entries:
            print(entry.priority, entry.source, entry.content)

if __name__ == "__main__":
    main()
```

[View the complete runnable example](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)

Observe: because `cwd = nested`, the discovery range is `root` → `nested`, and both files load; the `AGENTS.override.md` content contains `api_key=example-sensitive-value`, but `debug_context()` output is redacted, so the secret in `entry.content` is replaced with `[REDACTED]`.

### 10.4 Advanced example

Construct an explicit `AgentsMdLoader` with custom discovery, or read the structured fields of a debug snapshot directly:

```python
from super_harness import Agent, AgentsMdLoader

# Custom loader: smaller total cap, only recognize AGENTS.md
loader = AgentsMdLoader(root_markers=(".git",), max_bytes=16_384, filenames=("AGENTS.md",))
agent = Agent(provider, cwd="./src", agents_loader=loader)

thread = agent.thread()
snapshot = thread.debug_context()
print(snapshot.thread_id)
print(snapshot.history_messages)     # current history message count
print(snapshot.estimated_characters) # estimated total context chars (fragments + summaries)
for entry in snapshot.entries:
    print(entry.kind.value, entry.source, entry.priority)
```

`thread.debug_context()` returns `ContextDebugSnapshot(thread_id, entries, history_messages, estimated_characters)`, where `entries` are `ContextDebugEntry(kind, source, role, priority, content)` and the content has been redacted by `redact_text`. RAG/memory fragments are treated as **data, not instruction authority**, and cannot override developer or project instructions.

## 11. API quick reference

```python
# Agent
agent.thread()                                  # -> Thread (persists immediately if a store is configured)
agent.resume(thread_id)                         # -> Thread (requires a store)
agent.fork(thread_id)                           # -> Thread (= resume + fork)
agent.run(input, *, tools=(), output_schema=None)      # -> ModelResponse (fresh thread, sync)
agent.arun(input, *, tools=(), output_schema=None)     # -> ModelResponse (async)
agent.stream(input, *, tools=(), output_schema=None)   # -> Iterator[Event]
agent.astream(input, *, tools=(), output_schema=None)  # -> AsyncIterator[Event]

# Thread
thread.run(input, *, tools=(), output_schema=None)     # -> ModelResponse
thread.arun(input, *, tools=(), output_schema=None)    # -> ModelResponse
thread.stream(input, *, tools=(), output_schema=None)  # -> Iterator[Event]
thread.astream(input, *, tools=(), output_schema=None) # -> AsyncIterator[Event]
thread.start(input, *, tools=(), output_schema=None)   # -> TurnHandle
thread.compact(summary=None, *, retain_messages=None)  # -> tuple[Event, Event]
thread.acompact(summary=None, *, retain_messages=None) # -> tuple[Event, Event] (async, fires hooks)
thread.debug_context()                                  # -> ContextDebugSnapshot
thread.archive()                                        # archive (blocks new turns)
thread.fork(*, thread_id=None)                          # -> Thread (with parent_thread_id)
thread.aclose()                                         # fires SESSION_END hook

# TurnHandle
handle.events()                     # -> AsyncIterator[Event]
await handle.wait()                 # -> ModelResponse
await handle.steer(instruction)     # steer at a checkpoint
handle.cancel()                     # hard cancel
await handle.interrupt()            # interrupt

# SQLiteThreadStore
SQLiteThreadStore(path)             # usable as a context manager
store.save(thread)                  # persist a snapshot
store.load(thread_id)               # -> ThreadSnapshot
store.archive(thread_id, archived=True)
store.ids(include_archived=False)   # -> tuple[str, ...]
store.close()
```

## 12. Errors / timeouts / retries

- **Model errors**: transport errors, HTTP 429, and HTTP 5xx may retry (bounded budget); authentication and other HTTP 4xx fail immediately as `ModelError`.
- **Cannot run an archived thread**: calling any `run`/`arun`/`astream` on a thread with `archived=True` raises `RuntimeError("cannot run an archived thread")`.
- **Concurrency conflict**: starting another turn while one is active raises `RuntimeError("thread already has an active turn")`.
- **Empty input**: `turn input must be non-empty` (`ValueError`).
- **Empty steer instruction**: `handle.steer("")` raises `ValueError`.
- **Retention too small**: `retain_messages < 1` raises `ValueError`.
- **Resuming an unknown thread**: `store.load(unknown_id)` raises `KeyError`.
- **Sync method in an active event loop**: raises `RuntimeError`, telling you to use the async API.
- **Timeouts**: the runtime enforces an internal model-step ceiling `max_model_steps` (default 8); exceeding it terminates with `ToolError("tool loop exceeded maximum ...")`. For application-level timeouts use `asyncio.wait_for(handle.wait(), timeout=...)` together with `handle.cancel()`.
- **Cancellation semantics**: `interrupt` records `INTERRUPTED`, `cancel` records `CANCELLED`; when `resume` finds historical turns in `pending`/`running`/`waiting_tool`, it marks them `INTERRUPTED` with `"interrupted before resume"`.

## 13. Combining with other features

- **With tools/approval**: multiple turns on the same Thread can keep using `tools` and an `approval` policy; tool results are appended into `thread.messages`.
- **With Hooks**: `_astream` dispatches `SESSION_START`, `USER_PROMPT`, `TURN_START`, `BEFORE_MODEL`, `AFTER_MODEL`, `TURN_END`, `ERROR`, and `SESSION_END` across the turn lifecycle; compaction dispatches `PRE_COMPACT` / `POST_COMPACT` (via `acompact`). Use Hooks for policy interception and observability.
- **With observability**: pass an `observer` to `Agent`; every `astream` event passes through `observer.observe(event)`, enabling JSONL / OpenTelemetry integration.
- **With persistent memory**: combine `SQLiteThreadStore` with `MemoryManager`; `thread.messages` acts as durable thread-local conversation memory, while long-term facts go to `SQLiteMemoryStore`.
- **With Persona**: `Agent(..., persona=...)` stores non-secret persona metadata with each new Thread; `fork` deep-copies `metadata`.
- **With multi-agent**: every child Agent under `AgentManager` holds its own Thread; `fork`/`resume` can isolate different experiment branches.

## 14. Security notes

- `debug_context()` output is redacted by `redact_text` (matches `api_key`/`token`/`secret`/`password` and `sk-...` patterns); do not print unredacted `context` fragments to logs.
- The default extractive compaction **preserves** security-related lines (`permission`/`approval`/`sandbox`/`secret`/`credential`/`denied`) so permission state is not lost after compaction; be careful not to drop such information when providing a custom `summary`.
- The SQLite database file contains the full conversation history and summaries; treat it as sensitive data and store/back it up per your application's security policy.
- `store.ids()` lists only non-archived threads by default; archived thread history stays on disk but can no longer be run.
- Resuming uses stable IDs; do not leak unredacted content beyond `thread_id` into logs or external systems.

## 15. Troubleshooting

- **Sync method raises `RuntimeError: sync API cannot run inside an active event loop`** → use `arun`/`astream`/`await handle.wait()` instead.
- **`thread already has an active turn`** → the previous turn has not finished. Consume `handle.events()` or `await handle.wait()` before starting a new turn; do not call `start` again while a background handle is still active.
- **`cannot run an archived thread`** → the thread is archived. To continue, un-archive it with `store.archive(thread_id, archived=False)`.
- **`Agent.resume requires a SQLiteThreadStore`** → you forgot `store=` when constructing the `Agent`.
- **`unknown thread '<id>'` (KeyError)** → the `thread_id` does not exist in that database, or you switched database files.
- **Context is wrong after resume** → make sure the `Agent` you pass to `resume` is configured with the same `instructions`, `context`, and `cwd`/`agents_loader` as the original session; `resume` restores historical messages/turns/summaries, while context fragments come from the current `Agent` configuration.
- **Still over the window after compaction** → raise `retain_messages` or lower `compaction_threshold_chars`; confirm automatic compaction actually triggers (history char count exceeds the threshold).
- **`steer` raises `turn is no longer active`** → steering must happen while the turn is still active; once the model has finished, it is too late.
- **No `model.completed` in the stream** → if the consumer breaks early, a `GeneratorExit` fires and the turn is marked `INTERRUPTED`; consume the whole stream to avoid this.

## 16. Links

- Runnable examples referenced on this page:
  - [07_durable_thread/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/07_durable_thread/main.py)
  - [08_agents_context_debug/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/08_agents_context_debug/main.py)
  - [09_compaction_and_control/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/09_compaction_and_control/main.py)
  - [84_compaction_custom_summary.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/84_compaction_custom_summary.py)
  - [85_compaction_retention.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/85_compaction_retention.py)
  - [02_streaming/main.py](https://github.com/Sitozzmonash/superharness/blob/main/examples/02_streaming/main.py)
- Related pages: [API Reference](../api-reference.md) · [Examples index](../examples.md) · [Troubleshooting](../troubleshooting.md) · [User Guide Part I](../guide/part1-start.md)
- Related Internals: the low-level workings of the thread runtime, persistence, and compaction are covered in the Internals section.
