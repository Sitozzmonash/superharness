# Pinned Codex Research — CLI and Ecosystem UX

Date: 2026-08-26
Pinned commit: `7c6eb0eef113ddc16ae5b207ac9add364b489798`

## Inspected boundaries

- `codex-rs/cli/src/doctor.rs`: one structured report feeds human and JSON renderers;
  diagnostics do not repair state and expose safe cause/remediation details.
- `codex-rs/cli/tests/doctor_enterprise_network.rs`: integration tests parse `doctor --json`
  as a machine-readable contract.
- `codex-rs/tui/src/app.rs` and `app/agents_overview.rs`: resume rebuilds configuration,
  restores durable identity/history, then continues execution.
- `codex-rs/tui/src/app_event.rs`: plugin add/remove/update/detail and enablement are explicit,
  separate lifecycle operations.
- MCP checks in `doctor.rs`: configured executables and config are inspected, not repaired.

## Adopted behavior

- Human and JSON output render the same redacted values.
- Doctor is offline/read-only and distinguishes warnings from structural success.
- Thread inspection is provider-free; resume restores the Thread with an explicitly selected
  provider and prompt.
- Plugin install/update/remove never enables or imports plugin Python.
- Normalized failures return non-zero status and safe stderr.

## Intentional differences

- This Python library uses `argparse`, scoped filesystem state, and SQLite rather than Codex's
  TUI/app-server and rollout/config services.
- Skill and MCPB commands delegate to existing standards-based adapters; they are not Codex
  marketplace clones.
- The Official MCP Registry remains an optional replaceable preview client. Direct stdio, HTTP,
  import, and MCPB management remain usable offline.
- Provider tests accept credential environment-variable names only; values are never CLI
  arguments or output fields.
