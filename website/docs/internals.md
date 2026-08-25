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
