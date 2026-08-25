# Phase 7 Plan: Plugins and Hooks

1. Study pinned Codex manifest/path resolution, loader/manager/store, executor hook, timeout, policy, and rollback behavior.
2. Define all fourteen typed hook lifecycle events, ordered sync/async dispatch, explicit modification/denial, failure policies, timeout, cancellation, and traces.
3. Integrate hooks with Thread sessions/turns, prompts, model calls, tools, compaction, errors, and future subagent entry points.
4. Define a small Super Harness TOML manifest and best-effort Codex JSON importer with safe relative paths and framework-version validation.
5. Implement staged local/GitHub plugin install, explicit capability activation, namespacing, conflict rollback, disable, update, remove, and observability.
6. Run a pinned official Codex plugin repository E2E, then finish examples, docs, matrix, packaging, commit, and push.
