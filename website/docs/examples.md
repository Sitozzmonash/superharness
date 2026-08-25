---
title: Examples
---

Phase 1 includes three runnable DeepSeek examples under the repository `examples/` tree:

- `01_basic_agent`: minimal synchronous run.
- `02_streaming`: async correlated event consumption.
- `03_structured_and_tools`: strict JSON schema and normalized tool calls.

All require `DEEPSEEK_API_KEY`. Example source is compiled in CI; external requests are covered by the credential-gated real E2E suite.

Phase 2 adds:

- `04_custom_tool_loop`: complete DeepSeek function-call loop.
- `05_approval_and_registry`: callback denial before a side effect.
- `06_builtin_tools`: local file and Python process tools in a temporary workspace.

Only the DeepSeek example needs a credential; the approval and built-in examples run locally.

Phase 3 adds three credential-free examples:

- `07_durable_thread`: close/reopen SQLite, resume, and fork.
- `08_agents_context_debug`: hierarchical AGENTS discovery and redacted provenance.
- `09_compaction_and_control`: history compaction and TurnHandle interruption.
# Search, RAG, and vision examples

Examples `10`–`12` cover direct search, context injection, and tool exposure. Examples `13`–`15` cover direct RAG, RAG context, and RAG tools. Examples `16`–`18` cover local image, remote image, and vision tool use. Credentialed examples read only the documented environment variables.

Examples `19`–`21` cover working-memory state, LRU behavior, and Agent context. Examples `22`–`24` cover durable storage, cross-thread retrieval, and extraction/consolidation.
