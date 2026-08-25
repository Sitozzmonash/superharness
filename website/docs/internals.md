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
