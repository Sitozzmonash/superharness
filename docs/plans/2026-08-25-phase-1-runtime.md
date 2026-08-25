# Phase 1 Model/Provider and Basic Runtime Implementation Plan

> **For Codex:** Execute this plan in order and stop the phase only after every applicable acceptance gate has evidence.

**Goal:** Deliver provider-neutral model contracts, DeepSeek and OpenAI-compatible adapters, and an in-memory Agent/Thread/Turn runtime with streaming and structured-output/tool-call normalization.

**Architecture:** Immutable normalized model values isolate the runtime from provider wire formats. An async provider protocol feeds a streaming-first Agent runtime. Thread owns ordered messages and Turns; each Turn emits correlated immutable events and records one terminal state.

**Tech Stack:** Python 3.11+, Pydantic 2, HTTPX, pytest/pytest-asyncio, Ruff, Pyright.

---

### Task 1: Research gate

- Inspect pinned Codex provider, streaming, session, thread, protocol, and behavioral tests.
- Record reusable contracts, removed OpenAI coupling, Python design, differences, and tests in `docs/research/codex/`.

### Task 2: Provider-neutral model protocol

- Add immutable capabilities, messages, tools, tool calls, usage, request/response, and stream event types.
- Add the async `ModelProvider` protocol and public exports.
- Unit-test validation and immutability.

### Task 3: HTTP providers

- Implement Chat Completions and Responses request/response normalization.
- Implement SSE streaming, timeout, cancellation, bounded retry, authentication, and typed errors.
- Specialize the DeepSeek defaults and capability report.
- Test both wire formats against real local HTTP boundaries; keep real DeepSeek tests credential-gated.

### Task 4: Basic runtime

- Implement Turn states and diagnostic fields.
- Implement Thread history and streaming-first run methods.
- Implement Agent thread creation plus convenience run methods.
- Test lifecycle, multi-turn context, failure, cancellation, structured output, and tool-call normalization.

### Task 5: Product surface and acceptance

- Add three runnable examples covering basic run, streaming, and structured/tool output.
- Add user guide, internals guide, API reference, status evidence, and observability notes.
- Run install, lint, strict typing, unit/integration tests, credential-gated real E2E, docs build, secret scan, and coverage matrix reconciliation.
- Commit and push only after local evidence is clean.
