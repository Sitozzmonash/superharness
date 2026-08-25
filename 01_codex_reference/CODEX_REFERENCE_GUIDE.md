# Codex Reference Guide

## 1. Why Codex is a reference

Super Harness intentionally studies OpenAI Codex because Codex has mature patterns for:
- agent runtime loop;
- tools;
- sandbox/permissions;
- AGENTS.md;
- thread/session behavior;
- skills;
- MCP;
- web search;
- memory;
- plugins/hooks;
- multi-agent;
- event-oriented app-server interfaces;
- observability.

The goal is to preserve strong runtime ideas while removing OpenAI-specific assumptions and expressing them idiomatically in Python.

## 2. Pin a commit

Development repository should include:

```text
references/
├─ codex/                # git submodule or clone
└─ CODEX_PIN.md
```

Recommended workflow:

```bash
git clone https://github.com/openai/codex.git references/codex
cd references/codex
git rev-parse HEAD
```

Record commit SHA and date in `CODEX_PIN.md`.

If submodules are acceptable:

```bash
git submodule add https://github.com/openai/codex.git references/codex
git -C references/codex checkout <PINNED_SHA>
```

Never base behavior on an unspecified moving `main`.

## 3. Study source plus tests

For each Super Harness feature:
1. locate Codex implementation;
2. locate tests;
3. identify public behavior and invariants;
4. note configuration;
5. note event/protocol semantics;
6. note error/cancellation behavior;
7. note what is OpenAI-specific;
8. write Python-native design before implementation.

## 4. Do not mechanically translate Rust

Examples of legitimate redesign:
- Tokio task -> `asyncio.Task` / `TaskGroup`
- Rust enums -> Python `Enum` / tagged dataclasses
- traits -> `Protocol` / ABC
- channels -> async queues/event bus
- serde structs -> Pydantic/dataclass models
- crate boundaries -> Python packages/modules

Preserve behavior, not syntax.

## 5. Important current Codex references

As of 2026-08, the Codex Rust workspace contains dedicated areas such as:
- `core`
- `protocol`
- `tools`
- `sandboxing`
- `hooks`
- `plugin`
- `skills`
- `ext/skills`
- `ext/agent`
- `ext/memories`
- `ext/mcp`
- `ext/web-search`
- `model-provider`
- `thread-store`
- `state`
- `otel`
- `rollout`
- `rollout-trace`
- `secrets`
- `app-server`
- `connectors`

Always confirm paths against the pinned commit.

## 6. AGENTS.md behavior worth preserving

Current Codex source discovers `AGENTS.md` from project root down to the working directory and concatenates instructions in hierarchy order. It supports configured project root markers and a size budget, and has a local override filename (`AGENTS.override.md`).

Super Harness should preserve the useful behavior but document it better.

## 7. Multi-agent behavior worth preserving

Codex exposes autonomous operations conceptually equivalent to:
- spawn agent
- send input
- wait
- resume
- close
- interruption/cancellation

Super Harness should implement this style as the default autonomous orchestration mode while adding deterministic workflow and hybrid modes.

## 8. Web search difference

Do not copy Codex's provider/backend coupling. Super Harness must define `WebSearchProvider` and use Zhipu as V1 China-ready real provider.

## 9. References

Authoritative public sources to verify during development:
- https://github.com/openai/codex
- https://github.com/openai/codex/blob/main/codex-rs/Cargo.toml
- https://github.com/openai/codex/blob/main/codex-rs/core/src/agents_md.rs
- https://github.com/openai/codex/blob/main/AGENTS.md

If external behavior changed after the pinned commit, record the decision rather than silently mixing versions.
