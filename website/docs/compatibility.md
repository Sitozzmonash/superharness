---
title: Compatibility & Testing
---

The coverage matrix is a release gate. Mock-only paths do not count as real provider E2E evidence,
and no feature is marked complete until code, tests, documentation, examples, and observability are
all supported by evidence.

Phase 6 compatibility evidence includes a Skill installed from a pinned `openai/codex` GitHub subdirectory, a real stdio/HTTP server built with the official MCP 2.x SDK, an isolated official `mcp==1.29.1` server negotiating a representative 2025 protocol, and a live Official MCP Registry query. Set `SUPER_HARNESS_EXTERNAL_COMPAT=1` to run the network/dependency-backed checks; default tests skip them explicitly.

The primary HTTP target is MCP `2026-07-28`. Earlier 2025 protocol handling is intentionally delegated to the official SDK and kept in a separate compatibility test so legacy behavior cannot silently redefine the current transport contract.

Phase 7 consumes the official `openai/plugins` repository's `plugins/plugin-eval` directory at commit `11c74d6ba24d3a6d48f54a194cd00ef3beea18f9`. The Codex JSON importer supports identity/version/description, Skill roots, MCP path or inline definitions, passive assets/agents/commands, and retains other metadata. Codex apps/interface remain passive; command/MCP hook files are reported but never automatically executed.

The Super Harness TOML overlay adds Python Tool/hook entry points and a framework version specifier. This is an intentional extension because plugin formats are less standardized than Agent Skills or MCP.

Autonomous orchestration follows the pinned Codex collaboration operation set and state semantics but is a Python API rather than a wire-level Codex protocol clone. UUIDs replace Codex task paths; the child `AgentFactory` replaces internal model catalogs and executor environments. Full-history inheritance never silently changes provider/model policy because those choices remain explicit in the factory.

The real DeepSeek parent/child tool-chain test is credential gated. Without `DEEPSEEK_API_KEY`, local integration proves the complete model-requested Tool loop with deterministic providers but the matrix retains `Real E2E=TODO`.

The pinned Codex tree does not expose a generic executable DAG engine; its `update_plan` surface is a typed, event-emitting checklist. Super Harness intentionally extends those state/event principles with a provider-neutral Python workflow runtime. Phase 9 `Real E2E` is `N/A`: its product boundaries are the in-process scheduler and local atomic JSON store, both covered by integration tests without mocks or an external service.

Phase 10 composes the Phase 8 Agent lifecycle and Phase 9 workflow runtime without defining a new wire protocol. The autonomous node uses the same model-callable collaboration Tools tested under F27. Hybrid `Real E2E` is `N/A` because composition/cancellation/checkpointing are in-process control boundaries; live model behavior remains accurately represented by F27's credential-gated E2E status.

Phase 11 follows the pinned Codex separation between trace-safe metadata, richer local logs, validated metrics, optional exporters, and redacted secrets. It intentionally does not clone Codex account/session fields, Statsig defaults, or Rust tracing targets. OTEL network/provider setup remains application-owned; the framework boundary is tested through an injected standards-shaped tracer, so F32 `Real E2E` is `N/A`.

Security hardening remains `PARTIAL` overall: local path policy is not a Docker/VM sandbox, and explicitly enabled plugin Python runs in-process. These limitations are deployment controls, not silently represented as strong isolation.
