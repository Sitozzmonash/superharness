# Architectural Decision Log

This file records accepted project decisions. Newer explicit decisions override earlier entries when conflicts are recorded.

## ADR-001 — Product identity
**Decision:** Super Harness is a Python-native, Codex-inspired general-purpose Agent Runtime, not a Codex wrapper.

## ADR-002 — OpenAI optional
**Decision:** No core feature may require OpenAI services.

## ADR-003 — Main model
**Decision:** V1 real E2E default main provider/model is DeepSeek `deepseek-v4-flash`.

## ADR-004 — Vision
**Decision:** V1 requested vision model is Zhipu `glm-4v-flash`, behind an independent provider abstraction.

## ADR-005 — Search
**Decision:** V1 real E2E default Web Search provider is Zhipu Web Search API.

## ADR-006 — RAG
**Decision:** RAG is an external retrieval service. Super Harness sends query/top_n and receives Top-N text/documents. Core does not own vector DB, embedding, or indexing.

## ADR-007 — RAG testing
**Decision:** Build a real local HTTP mock RAG service and test transport end-to-end.

## ADR-008 — Multi-agent
**Decision:** Support all:
1. Codex-style autonomous subagents;
2. deterministic workflow;
3. hybrid.

## ADR-009 — AGENTS.md
**Decision:** Support Codex-like hierarchical AGENTS.md discovery and nested overrides.

## ADR-010 — Approval
**Decision:** Approval subsystem exists; V1 default policy is full access/permissive.

## ADR-011 — Skills
**Decision:** Adopt open Agent Skills/SKILL.md conventions and GitHub/local installation.

## ADR-012 — MCP
**Decision:** Use official Model Context Protocol, with stdio and Streamable HTTP first-class.

## ADR-013 — Plugins
**Decision:** Plugin system is required; aim for Codex-compatible import where practical but keep a documented Super Harness manifest.

## ADR-014 — Hooks
**Decision:** Hooks are required lifecycle extension points and distinct from passive events/approval.

## ADR-015 — Documentation
**Decision:** One documentation website deployed to GitHub Pages contains User Guide and Architecture & Internals plus Examples/API/Ecosystem/Testing/Troubleshooting.

## ADR-016 — Examples
**Decision:** Documentation core code must have corresponding runnable examples. At least 3 examples per major feature; more for complex orchestration/ecosystem features.

## ADR-017 — Completion gate
**Decision:** A feature is not DONE without implementation, tests, docs, API reference, examples, and coverage update.

## ADR-018 — Codex reference
**Decision:** Development uses a pinned OpenAI Codex commit accessible locally under `references/codex/`. Each major feature research cites the pinned source/tests.

## ADR-019 — Persistence
**Decision:** Default local persistence is SQLite; backend is abstractable.

## ADR-020 — Observability
**Decision:** Observability is built-in from early phases; structured events/logs/traces are not an afterthought.

## ADR-021 — Secret handling
**Decision:** Live API keys previously shared during planning are never copied into project material and should be rotated. Repository stores only env variable names.


## ADR-022 — Current MCP generation
**Decision:** Super Harness targets the current MCP `2026-07-28` protocol generation through a compatible SDK/adapter, while retaining isolated compatibility for representative older servers. The Agent core must not assume transport-level MCP sessions. MCPB is a supported portable local-server packaging path; Official MCP Registry support is optional-at-runtime and isolated because the registry remains preview.

## ADR-023 — Explicit release gates for cross-cutting features
**Decision:** Persona/role, configuration/profiles/secrets, retry/timeout/fallback/error semantics, security/hardening, and MCPB/Registry compatibility are explicit coverage-matrix rows and example/documentation obligations; they may not be treated as implicit subfeatures.
