---
title: Architecture & Internals
---

Super Harness uses an async-first, layered architecture. The runtime depends on the small `ModelProvider` protocol, never provider SDK response classes.

Phase 1 separates three layers:

1. Immutable values in `super_harness.models` define messages, schemas, calls, usage, responses, and stream events.
2. `OpenAICompatibleProvider` maps those values to Chat Completions or Responses HTTP payloads and maps replies back.
3. `Agent`, `Thread`, and `Turn` own orchestration, ordered history, lifecycle state, and correlated public events.

The stream path is authoritative. A provider stream succeeds only after `[DONE]` for Chat Completions or `response.completed` for Responses. Early closure is a retryable protocol failure within the configured stream budget. Cancellation propagates through the async generator to HTTPX.

The pinned-Codex evidence and deliberately removed coupling are recorded in `docs/research/codex/model-provider-and-streaming.md` and `docs/research/codex/agent-runtime-thread-turn.md`.

Phase 2 adds a deterministic `ToolRegistry` and one `ToolExecutor` pipeline: resolve → validate → approve → time-bound invoke → normalize → truncate. Denial and validation failures are returned as failed `ToolResult` data so the model can recover; task cancellation remains an exception and propagates to async handlers and subprocess cleanup.

Assistant tool calls and tool outputs are stored as neutral messages. Chat Completions receives assistant `tool_calls` plus `tool` messages; Responses receives `function_call` plus `function_call_output` items. A bounded model-step budget prevents an infinite tool loop.

The local sandbox resolves paths before I/O and terminates process groups on cancellation, but cannot constrain arbitrary child-process system calls. Shell and Python are disabled outside full-access mode. Research details are in `docs/research/codex/tool-runtime-sandbox-approval.md`.

Phase 3 stores transactional snapshots in versioned SQLite tables for Thread metadata, ordered messages, and ordered Turns. Tool calls, usage, structured output, summary IDs, timestamps, archive state, and fork lineage remain provider-neutral. A resumed pending/running/waiting-tool Turn is marked interrupted rather than silently completed.

Context assembly sorts typed fragments by authority, deduplicates stable `(kind, source, content)` identities, applies one total character budget, and retains provenance for redacted inspection. Project AGENTS files are lower authority than the current user message and are rendered earlier as marked user context.

Compaction persists an explicit summary and recent suffix. `TurnHandle` pumps the same authoritative Thread event stream; steering is queued until the next model-step checkpoint, while cancellation and interruption remain distinct terminal states. See `docs/research/codex/durable-thread-context-compaction.md`.
# External knowledge pipeline

`KnowledgeRouter` sits between the runtime and three async protocols: `WebSearchProvider`, `RAGProvider`, and `VisionProvider`. Concrete adapters own provider-specific HTTP shapes and return immutable neutral values. Search and RAG context is tagged `ContextKind.RAG` and rendered at user authority. Optional `KnowledgeTrace` sinks receive operation, provider, success, item count, and redacted metadata; credentials and image bodies are never included.

# Memory pipeline

Thread messages provide immediate conversation memory. `WorkingMemory` provides bounded LRU application state. Long-term memory uses an async `MemoryStore`; the built-in SQLite implementation stores immutable typed records under a normalized content fingerprint. `MemoryManager` invokes a replaceable extractor, upserts candidates, retrieves ranked matches from other threads, emits usage/traces, and converts matches to user-role `ContextKind.MEMORY` fragments.

# Skills and MCP

Skill discovery walks explicit, project, user, plugin, and system roots in precedence order. It parses only frontmatter during catalog construction. Activation reads the instruction body, while resource reads are separately confined to the Skill directory. Installation checks out Git into staging, resolves the requested revision, validates the package, and only then copies it to the installation root.

`MCPClient` wraps the official MCP Python `Client`. Stdio uses `StdioServerParameters`; HTTP supplies an isolated `httpx2` client to the SDK Streamable HTTP transport. Public methods bound pagination and cursors, apply operation timeouts, preserve cancellation, and normalize errors. `as_tools` translates server JSON Schema to the standard `Tool` surface while retaining the MCP server namespace and external-risk metadata.

MCPB inspection validates SHA-256, required manifest fields, safe paths, symbolic links, file count, and expanded size before extraction. Registry lookup remains behind the small replaceable `MCPRegistry` protocol because the Official Registry API is versioned independently of the runtime.

# Plugin and hook pipeline

`HookRegistry` dispatches registrations in `(priority, source, name)` order. Each callback receives a fresh immutable context view over the accumulated data. Async and sync handlers share one timeout/cancellation path. Failure policy is per registration; trace emission happens for success, denial, timeout, and error.

Thread startup dispatches session/prompt/turn hooks, each model step dispatches before/after hooks, `ToolExecutor` dispatches pre/post around execution after approval, and async compaction dispatches pre/post. Failure hooks receive the original exception. Subagent event types are defined now and are connected by the Phase 8 manager.

Plugin loading has two boundaries. Manifest load is data-only and validates paths/version requirements. Explicit activation imports Python entry symbols, namespaces Tools, registers hooks with forced `plugin:<name>` attribution, loads MCP config, and rolls back all earlier registrations if a later conflict occurs. Installer updates stage a complete replacement before swapping directories.
