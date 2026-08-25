# Codex research: agent runtime, Thread, and Turn

## Codex files inspected

- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/src/codex_thread.rs`
- `codex-rs/core/src/thread_manager.rs`
- `codex-rs/core/src/client_common.rs`
- `codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs`
- `codex-rs/app-server-protocol/src/protocol/v2/turn.rs`
- `codex-rs/protocol/src/protocol.rs`
- `codex-rs/protocol/src/models.rs`

## Codex tests inspected

- `codex-rs/core/src/thread_manager_tests.rs`
- `codex-rs/core/tests/suite/tools.rs`
- `codex-rs/core/tests/suite/json_result.rs`
- `codex-rs/core/tests/suite/stream_no_completed.rs`

## Behavioral contract

- A Thread owns ordered history and turns; a Turn owns one user-initiated execution.
- Turn state moves through explicit lifecycle states and records timestamps and errors.
- The runtime appends user input, invokes the model, records assistant output, and continues only when normalized calls require another orchestration step.
- Events carry correlation identifiers and expose lifecycle without requiring clients to inspect internal state.
- A turn-scoped provider session is reused for all model calls made by that turn.
- Cancellation and interruption are observable terminal outcomes.

## Invariants

- History order is stable and append-only during a basic in-memory run.
- Exactly one terminal state is recorded per turn.
- Failed or cancelled turns retain diagnostic state.
- Model deltas precede the completed model event; the turn completes only after provider completion.
- Public sync wrappers must not nest an event loop.

## OpenAI coupling removed

Thread and Turn store provider-neutral messages and model results. They do not store Responses API objects, OpenAI item variants, account metadata, or transport session state.

## Python design

- `Agent` owns instructions and a `ModelProvider` and creates in-memory `Thread` objects.
- `Thread` exposes `arun/run` and `astream/stream`; each invocation creates a `Turn` and appends normalized messages.
- `Turn` uses a typed status enum, UTC timestamps, result/error fields, and emitted immutable `Event` values.
- The streaming API is the source of truth; non-streaming collection is a thin consumer of it.

## Differences and extensions

- Phase 1 deliberately stops before executing tools; it normalizes tool calls for the Phase 2 executor.
- Persistence, resume/fork/archive, steering, compaction, and context fragments remain Phase 3 work.
- Events use stable dotted names and the Phase 0 generic immutable event envelope.

## Tests to reproduce

- Basic async and sync runs append user and assistant history.
- Repeated runs reuse Thread history but create distinct ordered turns.
- Streaming emits turn/model lifecycle plus text deltas in order.
- Provider failure marks the turn failed and emits one failed terminal event.
- Cancellation marks the turn cancelled and preserves history.
- Sync methods reject use from an already-running event loop with a helpful error.

