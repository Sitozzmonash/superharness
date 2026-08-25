# Phase 3 Durable Thread and Context Implementation Plan

> **For Codex:** Execute in order and retain local versus external evidence separately.

**Goal:** Add SQLite durability, resume/fork/archive, structured context and AGENTS discovery, compaction, debug snapshots, and active-turn controls.

**Architecture:** Thread remains the live orchestration boundary. A versioned storage protocol persists provider-neutral snapshots. Context is assembled from typed, provenance-bearing fragments. TurnHandle owns event delivery and safe control signals; compaction replaces an old prefix with an explicit summary.

**Tech Stack:** Python stdlib sqlite3/asyncio/pathlib, Pydantic 2, pytest.

---

### Task 1: Context and AGENTS.md

- Implement typed fragments, precedence, deduplication, budgeting, redaction, and debug snapshots.
- Implement root-to-cwd AGENTS discovery with override and byte limit.
- Integrate rendered context into model requests and test precedence/provenance.

### Task 2: SQLite Thread store

- Add versioned schema and transactional snapshots.
- Persist/reload messages, tool calls, turns, summaries, metadata, archive, and lineage.
- Add Agent create/resume/fork APIs and restart-level integration tests.

### Task 3: Compaction

- Add explicit summaries, recent suffix retention, security-fact preservation, and automatic thresholds.
- Emit compaction lifecycle events and persist boundaries.

### Task 4: Active-turn controls

- Add TurnHandle event stream, await result, steer, interrupt, and cancel.
- Apply steering at safe checkpoints and preserve distinct terminal diagnostics.

### Task 5: Acceptance

- Add examples and complete user, internals, API, status, and observability docs.
- Run quality, restart-level SQLite integration, docs, secret scan, wheel install, and coverage reconciliation.
- Commit and push verified work; keep external provider gates explicit.
