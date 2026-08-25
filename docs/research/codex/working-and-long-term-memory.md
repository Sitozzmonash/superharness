# Codex Research: Working and Long-term Memory

## Codex files inspected

- `codex-rs/memories/README.md`
- `codex-rs/ext/memories/src/schema.rs`
- `codex-rs/ext/memories/src/local/search.rs`
- `codex-rs/memories/write/src/storage.rs`
- `codex-rs/memories/write/src/phase1.rs`
- `codex-rs/memories/write/src/phase2.rs`

## Codex tests inspected

- `codex-rs/memories/write/src/storage_tests.rs`
- `codex-rs/memories/write/src/guard_tests.rs`
- `codex-rs/ext/memories/src/tests.rs`
- `codex-rs/app-server/tests/suite/v2/memory_reset.rs`
- `codex-rs/app-server/tests/suite/v2/thread_memory_mode_set.rs`

## Behavioral contract

Memory is durable, searchable data derived from eligible conversations. Codex separates per-thread extraction from globally serialized consolidation, bounds work, avoids duplicate claims, ranks useful/recent memories, preserves stable artifacts, and injects read results as developer-described but citation-bearing memory context. Local search is deterministic, bounded, path scoped, and validates empty queries/windows/cursors.

## Important invariants

- Conversation history remains the immediate working-memory source of truth.
- Long-term records are provider-neutral and never store clients or credentials.
- Extraction is conservative and replaceable; consolidation deduplicates normalized content.
- Cross-thread retrieval can exclude the current source thread.
- Retrieved memory is user-role data, not instruction authority.
- SQLite schema versions reject newer incompatible databases.
- Search is deterministic, bounded, records usage, and survives restart.

## OpenAI-specific coupling to remove

Codex extraction/consolidation uses internal model prompts, state job leases, rollout JSONL, Codex home layout, and internal sub-agents. Super Harness exposes `MemoryExtractor` and `MemoryStore` protocols. The built-in extractor is credential-free, while applications may substitute a model-backed implementation without changing persistence or retrieval.

## Python-native design

`WorkingMemory` is a bounded LRU key/value store that emits a `ContextFragment`. `SQLiteMemoryStore` implements async remember/get/search/forget operations over a WAL database. `MemoryManager` runs an extractor, consolidates via a normalized unique fingerprint, retrieves cross-thread matches, emits `MemoryTrace`, and produces low-authority context fragments.

## Differences/intentional extensions

- Uses one portable SQLite file rather than a generated Markdown/git workspace.
- Provides typed kinds, tags, importance, metadata, usage count, and last-access time.
- Ships a minimal explicit `Remember:` extractor to avoid silently inventing user facts.
- Keeps extraction pluggable for later model-backed implementations.
- Provides a direct working-memory API in addition to durable Thread conversation history.

## Tests to reproduce behavior

- Working-memory LRU eviction, access refresh, deletion, and user-role context rendering.
- SQLite deduplication, metadata preservation, cross-thread exclusion, restart, delete, and newer-schema rejection.
- Explicit extraction, ignored transient text, custom extractor replacement, trace emission, and consolidation.
- Long-term retrieval into an independent Agent whose answer requires a fact from another thread.
