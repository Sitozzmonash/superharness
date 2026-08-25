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
