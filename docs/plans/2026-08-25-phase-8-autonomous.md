# Phase 8 Plan: Autonomous Multi-Agent

1. Study pinned Codex collaboration tool handlers, live Agent state, resume/close, usage hints, limits, cancellation, and notifications.
2. Define typed parent/child metadata, statuses, spawn requests, bounded results, limits, context inheritance, and aggregate events.
3. Implement concurrent spawn/send/wait/resume/interrupt/close with selective conditions, subtree cancellation, budgets, and depth/active/total guards.
4. Attach collaboration operations as ordinary model-callable Tools to root and child Agents so delegation is autonomous rather than a static router.
5. Integrate subagent hooks, accumulated usage, concise result aggregation, delta suppression, and trace-tree inspection.
6. Verify a model-driven full chain, add five examples and real DeepSeek E2E gating, then finish docs, matrix, package gates, commit, and push.
