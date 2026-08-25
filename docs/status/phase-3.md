# Phase 3 Status

Date: 2026-08-25

## Outcome

Phase 3 is implemented and passes all local acceptance gates. It remains `PARTIAL` in the release matrix because no real external-model E2E was run; the only configured external provider test is still skipped without `DEEPSEEK_API_KEY`.

Delivered: SQLite durability, restart/resume/fork/archive, provider-neutral snapshot serialization, structured context and debug snapshots, hierarchical AGENTS discovery, manual/automatic compaction, TurnHandle streaming and controls, and one-active-turn enforcement.

## Acceptance evidence

| Gate | Result | Evidence |
|---|---|---|
| Pinned Codex research | PASS | Thread store, context fragments, AGENTS, context manager, compaction, truncation, and associated tests recorded |
| Ruff format/lint | PASS | All project Python and examples clean |
| Pyright strict | PASS | 0 errors, 0 warnings |
| Pytest | PARTIAL | 53 passed; one DeepSeek external E2E skipped for missing credential |
| SQLite restart integration | PASS | Store closed/reopened; stable ID, instructions, metadata, messages, tool calls, turns, structured values, and summaries restored |
| Fork/archive | PASS | Independent child history with parent lineage; archived Thread retained but rejects new run |
| AGENTS filesystem integration | PASS | `.git` root, root-to-cwd order, override precedence, byte cap, provenance, and no parent escape |
| Compaction | PASS | Automatic lifecycle events; recent suffix and security/permission facts preserved; summary persisted |
| Turn controls | PASS | Safe-checkpoint steer, cancel, interrupt, stream-close interruption, and concurrent-turn rejection |
| Context debug security | PASS | Secret-like values redacted from snapshot content and repr |
| Local examples | PASS | Three credential-free examples executed successfully |
| Secret scan | PASS | High-confidence scan passed |
| Docusaurus build | PASS | Client/server bundles and static output built successfully |

## Persistence contract

SQLite schema version 1 separates Thread metadata from ordered message and Turn rows. Each save is one transaction. Snapshots include provider-neutral roles, assistant tool calls, tool outputs, usage, structured JSON, timestamps, summaries, archive state, metadata, and lineage. Provider instances, credentials, HTTP clients, and live tasks are never persisted.

An unfinished persisted Turn is marked `interrupted` on resume. Fork copies immutable history and deep-copies mutable Turn/metadata state under a new ID.

## Context and control boundaries

- Project instructions are rendered before the current user message so later current input has narrower precedence.
- Memory/RAG remain data fragments, not authority.
- Debug snapshots redact common credential assignments and `sk-` tokens.
- Steering waits for the next model-step checkpoint; it does not mutate an in-flight provider request.
- Closing an event stream marks the Turn interrupted; cancel and interrupt retain distinct states.

## Deliberately deferred

- High-quality model-based compaction and token-provider accounting.
- Persistent queueing of steer instructions across process death.
- SQLite migrations beyond schema version 1 and remote stores.
- Real external-model persistence/context E2E, pending credential.
