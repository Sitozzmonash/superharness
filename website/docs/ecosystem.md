---
title: Ecosystem
---

Super Harness will consume existing Agent Skills, Model Context Protocol, Python entry-point, and
Codex-compatible plugin conventions before defining project-specific formats.

## Agent Skills

Phase 6 consumes standard `SKILL.md` frontmatter and directory resources. Local and HTTPS Git/GitHub installation is supported, including a repository subdirectory at a branch, tag, or commit. Install provenance is stored in `.super-harness-source.json`.

## Model Context Protocol

Both stdio and Streamable HTTP use the official Python SDK. Common `mcpServers` JSON can be imported. Remote tools are exposed through the normal Super Harness tool abstraction, while resources and prompts remain available through explicit MCP client methods.

## MCPB and Registry

`.mcpb` archives are inspected and installed with integrity and archive-safety checks. The Official MCP Registry preview endpoint is available through a replaceable adapter; Registry discovery does not imply trust or automatic installation.

## Plugins and hooks

Super Harness plugins use `.super-harness/plugin.toml`; `.codex-plugin/plugin.json` is imported best-effort. Every relative capability path must begin with `./` and remain under the plugin root. Local and pinned HTTPS Git/GitHub sources are supported with source metadata and explicit enable.

Python tool packages may also expose conventional entry points in future releases, but Phase 7 does not auto-discover or execute installed package entry points. Plugin Python is imported only for explicitly enabled manifest entries.
