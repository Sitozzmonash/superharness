# Phase 12 — CLI and Ecosystem UX

Date: 2026-08-26

## Contract

Deliver the roadmap's complete command surface without duplicating the validated ecosystem
implementations from Phases 6 and 7:

- `doctor`
- `skill add/list/info/update/remove`
- `mcp add/list/inspect/remove/search/import`, including MCPB and Registry paths
- `plugin add/list/info/update/remove`
- `thread inspect/resume`
- `provider test`

Project scope uses `<project>/.super-harness`; `--global` uses the user installation root.
Machine-readable `--json` output is stable and all human/JSON diagnostics are redacted.

## Implementation route

1. Add a small persistent CLI state adapter for MCP configuration and scoped paths.
2. Add transactional Skill update support based on recorded source metadata.
3. Implement an `argparse` command tree that delegates to existing installers, registry,
   persistence, and provider APIs.
4. Add focused command tests, including failure exit codes, scope isolation, redaction,
   MCP import/bundle handling, Thread inspection, and mocked provider/registry boundaries.
5. Add at least three runnable CLI examples and synchronize the website, README, coverage
   matrix, and status evidence.
6. Run Ruff, Pyright, full pytest, documentation build, secret scan, package build, and CLI
   smoke tests before commit and push.

## Safety boundaries

- Never print environment values, API keys, MCP headers, or MCP environment values.
- Do not execute a plugin during add/list/info/update/remove.
- Registry availability is optional and errors are normalized.
- `thread resume` requires an explicit prompt and provider configuration; inspection remains
  offline.
- Destructive removals target only a validated named installation inside the selected scope.
