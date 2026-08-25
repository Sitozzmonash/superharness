---
title: API Reference
---

## Agent

- `Agent(provider, *, instructions=None)`
- `run/arun(input, *, tools=(), output_schema=None) -> ModelResponse`
- `stream/astream(input, *, tools=(), output_schema=None) -> Event iterator`
- `thread() -> Thread`
- `aclose()`

## Thread and Turn

`Thread` offers the same run and stream methods while retaining ordered `messages` and `turns`. `TurnStatus` includes pending, running, waiting-tool, completed, failed, interrupted, and cancelled.

## Providers

`ModelProvider` defines `name`, `capabilities`, `complete`, `stream`, and `aclose`. `OpenAICompatibleProvider` supports `WireAPI.CHAT_COMPLETIONS` and `WireAPI.RESPONSES`. `DeepSeekProvider` supplies DeepSeek defaults.

## Normalized values

Public immutable values are `Message`, `ToolDefinition`, `ToolCall`, `Usage`, `ModelCapabilities`, `ModelRequest`, `ModelResponse`, and `ModelStreamEvent`.

## Events and errors

Every `Event` has an ID, timezone-aware timestamp, optional correlation IDs, and read-only payload. Provider failures use `ModelError`; public error messages and details exclude credential values.

## Tools

- `@tool(...) -> Tool`: derives arguments and JSON Schema from a typed sync or async callable.
- `ToolRegistry`: `register`, `unregister`, `get`, `enable`, `disable`, `list`, `search`, and `definitions`.
- `ToolExecutor.execute(ToolCall) -> ToolResult`: validation, approval, timeout, invocation, normalization, and truncation.
- `ApprovalPolicy`: `full_access`, `deny_all`, or callback policy.
- `LocalSandbox(workspace, mode=...)`: checked path resolution and cancellable local subprocesses.
- Built-ins: `file_read_tool`, `file_write_tool`, `file_search_tool`, `shell_tool`, `python_tool`, and `basic_builtin_tools`.

`ToolResult` exposes call ID, name, bounded output, success, truncation flag, original character count, and normalized error type.

## Durable Thread and context

- `SQLiteThreadStore(path)`: `save`, `load`, `archive`, `ids`, `close`, and context-manager support.
- `Agent.resume(thread_id)` / `Agent.fork(thread_id)`.
- `Thread.archive`, `fork`, `compact`, `debug_context`, and `start`.
- `ContextFragment`, `ContextKind`, `ContextAssembler`, `ContextDebugSnapshot`, and `AgentsMdLoader`.
- `ContextSummary`: immutable summary ID, content, covered-message count, and UTC timestamp.
- `TurnHandle.events`, `wait`, `steer`, `cancel`, and `interrupt`.
# Knowledge API

- `ZhipuWebSearchProvider.search(query, top_n=5) -> SearchResponse`
- `HTTPRAGProvider.retrieve(query, top_n=3) -> tuple[RAGDocument, ...]`
- `ZhipuVisionProvider.analyze(image, prompt) -> VisionResult`
- `KnowledgeRouter.search_context(...)` and `rag_context(...)`
- `KnowledgeRouter.tools() -> tuple[Tool, ...]`

Provider failures raise `SearchError`, `RAGError`, or `VisionError`. Cancellation propagates as `asyncio.CancelledError`.

# Memory API

- `WorkingMemory(max_items=64)`: `set`, `get`, `delete`, `clear`, `snapshot`, `context`.
- `SQLiteMemoryStore(path)`: async `remember`, `get`, `search`, `forget`, `close`.
- `MemoryManager(store, extractor=None, trace_sink=None)`: `consolidate` and `retrieve_context`.
- `MemoryCandidate`, `MemoryRecord`, `MemoryMatch`, `MemoryKind`, and `MemoryTrace` are provider-neutral values.
