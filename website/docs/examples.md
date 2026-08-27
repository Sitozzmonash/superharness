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

# Skills and MCP examples

Examples `25`–`27` cover Skill discovery, progressive activation/resources, and installation. Examples `28`–`30` cover stdio tool discovery/calls/resources. Examples `31`–`33` cover Streamable HTTP negotiation, calls, and prompts. Examples `34`–`36` cover common config import, safe MCPB installation, and Official Registry search.

# Plugin and hook examples

Examples `37`–`39` cover plugin installation/provenance, capability activation, and disable/update/remove lifecycle. Examples `40`–`42` cover lifecycle logging, pre-tool policy denial, and plugin-contributed hook registration.

# Autonomous multi-Agent examples

Examples `43`–`47` cover model-driven research decomposition, a coding/review/test team, parallel critics, child follow-up/resume, and budget/interruption. They use DeepSeek and require `DEEPSEEK_API_KEY`; the deterministic integration suite exercises the same operations without external credentials.

# Workflow examples

Examples `48`–`52` are credential-free and cover a three-step sequence, concurrent fan-out/join, a boolean conditional, a named router, and retry plus a strictly bounded loop. Each file can run directly with Python after installing the package in editable mode.

# Hybrid examples

Examples `53`–`56` are credential-free and cover an autonomous Agent node, a durable nested workflow, a workflow Agent that autonomously spawns and joins two specialists through collaboration Tools, and parent/child failure-resume from JSON checkpoints.

# Observability and hardening examples

Examples `57`–`59` cover human/JSONL output, trace-tree and metric inspection, and optional OTEL export. Examples `60`–`62` cover recursive secret masking, restricted local sandbox denial, user-role external data, and malicious Tool-name rejection. All six are credential-free.

# CLI examples

Examples `63`–`65` are credential-free and cover JSON doctor diagnostics, the local Skill CLI
lifecycle, and provider-free durable Thread inspection.

# Release-gate examples

Examples `66`–`68` cover dynamic registration, metadata-only lazy discovery, and namespaced lazy
loading. Examples `69`–`71` cover secure Docker argv, allowlisted environment forwarding, and a
conditional real run that never pulls an image. Examples `72`–`74` cover priority, async context,
defaults, and observation. Examples `75`–`77` cover identity, scopes, and named role templates.
Examples `78`–`80` cover profiles, precedence, and masked secret providers. Examples `81`–`83`
cover ordered fallback, safe stream switching, and timeout normalization.

Examples `84`–`91` close earlier local documentation gaps with custom/retained compaction,
file-search and process built-ins, allow/deny approval, and AGENTS override/repository-boundary
discovery. All Phase 13 examples are credential-free; example 71 prints an explicit skip when the
Docker runtime or pre-existing `alpine:3.20` image is absent.
