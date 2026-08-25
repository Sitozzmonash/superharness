---
title: Troubleshooting
---

During Phase 0, verify Python 3.11+, Node 20+, and an editable development install. Provider,
sandbox, MCP, and workflow troubleshooting will be added with the corresponding real features.

## Multi-Agent limits

`MultiAgentError` reports which guard rejected a spawn: active children, total children, depth, total tokens, or total elapsed time. Inspect `manager.list_agents()`, `manager.tokens_used`, and `manager.event_history()` before increasing limits. A child marked `budget_exhausted` completed its request but exceeded its allocation; later spawns may be blocked by the total budget.

If `wait` returns active snapshots, its timeout expired; it does not cancel children. Use a longer event-driven wait, `interrupt_agent` for one child, or `cancel(parent_id)` for a subtree. Do not loop with very short waits.

If a model never delegates, confirm `expose_tools=True` and inspect the root Thread's tool definitions. Tool-name conflicts fail manager construction rather than silently replacing application tools. Real DeepSeek delegation also requires `DEEPSEEK_API_KEY` and a model response that chooses the collaboration Tools.
