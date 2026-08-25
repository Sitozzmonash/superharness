# Codex research: durable Thread, context, AGENTS.md, and compaction

## Codex files inspected

- `codex-rs/thread-store/README.md`
- `codex-rs/thread-store/src/lib.rs`
- `codex-rs/thread-store/src/in_memory.rs`
- `codex-rs/thread-store/src/live_thread.rs`
- `codex-rs/thread-store/src/types.rs`
- `codex-rs/context-fragments/src/fragment.rs`
- `codex-rs/context-fragments/src/additional_context.rs`
- `codex-rs/core/src/agents_md.rs`
- `codex-rs/core/src/context_manager/history.rs`
- `codex-rs/core/src/context_manager/normalize.rs`
- `codex-rs/core/src/compact.rs`
- `codex-rs/core/src/thread_manager.rs`
- `codex-rs/core/src/thread_rollout_truncation.rs`

## Codex tests inspected

- `codex-rs/core/src/agents_md_tests.rs`
- `codex-rs/core/src/context_manager/history_tests.rs`
- `codex-rs/core/src/compact_tests.rs`
- `codex-rs/core/src/thread_manager_tests.rs`
- `codex-rs/core/src/thread_rollout_truncation_tests.rs`
- `codex-rs/core/tests/suite/agents_md.rs`
- `codex-rs/core/tests/suite/compact_resume_fork.rs`
- `codex-rs/thread-store/src/local/model_context_tests.rs`
- `codex-rs/thread-store/src/local/revert_thread_tests.rs`

## Behavioral contract

- Thread ID is the durable handle; storage owns history and explicit metadata without inferring hidden mutations.
- Active sessions append canonical history and update metadata through separate, atomic APIs.
- Resume restores the original ID and history; fork creates a new ID from an explicit snapshot boundary; archive is metadata, not deletion.
- Context fragments retain role, classification, provenance, and marker identity instead of becoming untraceable string concatenation.
- AGENTS instructions are discovered from project root to cwd, never above the root, with local override precedence and a total byte budget.
- Compaction preserves a summary plus the recent suffix and records an explicit boundary/event.

## Important invariants

- Persisted order and IDs survive process restart.
- A failed write rolls back atomically.
- Resume/fork cannot restore an in-progress turn as silently completed.
- Context ordering follows authority precedence; retrieved data is never promoted to instructions.
- Debug context is redacted and includes provenance.
- Compaction never discards permission/security state without retaining it in the summary.
- Interrupt/cancel retains diagnostics; steering is injected only at safe checkpoints.

## OpenAI-specific coupling to remove

Persistence stores neutral messages, tool calls, turns, summaries, metadata, and timestamps. It does not persist Responses API items, rollout JSONL wire objects, OpenAI IDs, account state, or ChatGPT-specific metadata.

## Python-native design

- `SQLiteThreadStore` uses versioned SQLite tables and transactional full snapshots for the initial durable implementation.
- `Agent` creates, resumes, and forks Threads using its live provider/tool configuration.
- `ContextFragment` and `ContextAssembler` implement authority ordering, deduplication, budgeting, provenance, and safe rendering.
- `AgentsMdLoader` discovers `.git` root and loads `AGENTS.override.md` before `AGENTS.md` at each hierarchy level within a byte cap.
- `Thread.compact` records an extractive or supplied summary and keeps a recent message suffix; automatic compaction is threshold-driven.

## Differences/intentional extensions

- SQLite is the canonical V1 store rather than paired JSONL plus SQLite metadata.
- The default local compactor is deterministic and extractive; applications may provide a higher-quality summary explicitly without forcing another provider call.
- Debug snapshots are first-class public values from Phase 3 rather than an app-server-only diagnostic surface.

## Tests to reproduce behavior

- Create/save/reopen/resume with stable IDs, messages, turns, tool calls, and summaries.
- Fork isolation and lineage; archive blocks new runs but does not delete history.
- Transaction rollback and schema migration version.
- Context precedence, deduplication, budget, provenance, and secret redaction.
- Root/nested AGENTS order, override precedence, byte limit, and no walk above root.
- Manual and automatic compaction preserve recent suffix plus security facts.
- Cancel, interrupt, and steer state/events at safe checkpoints.

