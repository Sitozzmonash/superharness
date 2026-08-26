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

# Autonomous orchestration

`AgentManager` keeps mutable task records private and returns immutable snapshots/results/events. Every child owns an independent Agent and Thread created by an application factory. Spawn validates the full limit set before insertion, emits `SUBAGENT_START`, and schedules `_run` as an asyncio Task. Start-hook failure removes the pending record; end-hook failure still notifies waiters.

Selective wait and event streaming use asyncio Conditions, not polling. Thread events are wrapped as ordered `AgentEvent` values, but token deltas are filtered unless `include_child_deltas=True`. Model usage is accumulated from every `model.completed` event. Terminal child output is bounded and includes neutral Usage, artifact/reference fields, and descendant Thread IDs.

Collaboration operations are normal typed Tools registered in each participating Agent's existing registry. This reuses validation, approval, timeout, tool-result correlation, and model continuation. Parent/subtree cancellation walks descendants deepest first. Resume retains the same Thread history; cross-process state recovery is added with the persistence expansion.

# Deterministic workflows

`Workflow.validate` performs endpoint/identity checks and Kahn DAG validation before any handler runs. Loops are node-local constructs with mandatory finite bounds rather than graph back-edges. Retry budgets are node-local too, and construction rejects more than one attempt unless the node explicitly declares idempotency.

The engine evaluates dependency-ready nodes in batches. Independent nodes become asyncio Tasks behind a concurrency semaphore; a join becomes ready only after all incoming sources reach terminal state and at least one route is active. Inactive conditional branches are marked skipped, allowing the selected branch to rejoin without pretending the unselected handler ran.

Every stable batch is serializable as a versioned `WorkflowRun`. The JSON store writes a temporary file and atomically replaces the checkpoint. Resume keeps completed results/state and resets only unfinished, failed, skipped, or interrupted nodes. Event history uses monotonic per-run sequence numbers and correlates workflow/node lifecycle, route, retry, failure, and interruption.

# Hybrid boundary

`AutonomousAgentNode` delegates to the normal `AgentManager`; it does not simulate a model response or bypass Tool execution. The node waits for its child and all discovered descendants. Active descendants after a bounded wait are cancelled, and any non-completed descendant fails the node. Forwarded observations include IDs and lifecycle types but omit child text/token payload bodies.

`SubworkflowNode` derives `<parent-run>-<node>` as a safe stable child identity. With a child `JSONWorkflowStore`, a repeated parent node resumes that checkpoint and forwards only event sequences newer than the loaded snapshot. Task cancellation propagates through both engines; each engine records its own interruption before the parent node exits.

# Observability and redaction

The observation path is downstream of immutable lifecycle events. It never controls scheduling or provider responses. One event is normalized, content-filtered, recursively redacted, correlated into a span, counted, logged, and optionally exported. Export errors are collected and fail open unless `strict_export=True`.

Default filtering removes prompt/model/request/response/tool argument/result bodies and token deltas. The redactor then masks configured exact values, sensitive keys, common assignments, bearer/JWT/OpenAI/GitHub-shaped tokens, wrappers, and exception messages. Traversal is cycle aware and bounded by depth/items/string length.

Trace parents follow thread→turn→model/tool, workflow→node, and Agent parent→child where live correlation exists. Search/RAG/Vision/MCP use unique operation IDs. Metrics remain local dependency-free samples; optional OTEL span export delegates provider/network configuration to the application.
