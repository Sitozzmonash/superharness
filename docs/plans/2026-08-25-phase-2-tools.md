# Phase 2 Tool Runtime Implementation Plan

> **For Codex:** Execute this plan in order and retain evidence for every applicable gate.

**Goal:** Deliver typed function tools, deterministic registry and execution, approval and local sandbox controls, basic built-ins, bounded output, and the iterative model/tool runtime loop.

**Architecture:** Tool metadata and executable handler remain one object. A registry resolves calls; a single executor composes validation, approval, timeout, sandbox-aware execution, normalization, truncation, and events. Thread performs a bounded streaming model/tool loop using neutral messages.

**Tech Stack:** Python 3.11+, asyncio subprocesses, Pydantic 2, pytest/pytest-asyncio.

---

### Task 1: Tool definition and registry

- Implement `@tool`, typed schema generation, metadata, and provider conversion.
- Implement deterministic namespace-aware registry with conflict, state, list, and search behavior.
- Test before adding execution.

### Task 2: Approval, sandbox, and executor

- Implement full-access, deny, and callback approval decisions.
- Implement local path resolution for read-only, workspace-write, and full-access modes.
- Implement argument validation, timeout/cancellation, output normalization, head/tail truncation, and correlated events.
- Test denied side effects, timeout, cancellation, path escapes, and truncation.

### Task 3: Built-in tools

- Add file read/write/search tools.
- Add shell and Python subprocess tools with cancellation cleanup and explicit local-sandbox limitation.
- Exercise real local filesystem and process boundaries.

### Task 4: Agent tool loop

- Extend neutral messages for assistant tool calls and tool outputs on both wire APIs.
- Execute normalized calls, append results, and continue until a final answer or bounded-step error.
- Test multiple tool calls and failures against a real local HTTP model fixture.

### Task 5: Acceptance

- Add at least three runnable examples and complete user, internals, API, observability, and status docs.
- Run lint, strict typing, unit/integration tests, real DeepSeek tool-loop E2E when credentialed, docs build, secret scan, wheel install, and matrix reconciliation.
- Commit and push only verified evidence.
