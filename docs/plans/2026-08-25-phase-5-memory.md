# Phase 5 Plan: Memory

1. Study pinned Codex extraction, consolidation, storage, search, reset, and memory-mode behavior.
2. Add bounded working memory while retaining durable Thread messages as conversation memory.
3. Define provider-neutral memory values and an async `MemoryStore` protocol.
4. Implement a versioned WAL-backed SQLite store with normalized deduplication, ranking, usage accounting, cross-thread filtering, and deletion.
5. Add a pluggable extraction/consolidation pipeline, conservative default extractor, context injection, and traces.
6. Verify restart and a cross-thread Agent chain, then complete docs, examples, matrix, packaging gates, commit, and push.
