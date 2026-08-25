# Codex Research: Deterministic Workflow

## Codex files inspected

- `codex-rs/protocol/src/plan_tool.rs`
- `codex-rs/core/src/tools/handlers/plan.rs`
- `codex-rs/core/src/tools/handlers/plan_spec.rs`
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/protocol/src/prompts/base_instructions/default.md`

## Codex tests inspected

- `codex-rs/core/tests/suite/tool_harness.rs`
- `codex-rs/core/tests/suite/code_mode.rs`
- `codex-rs/core/src/tools/spec_plan_tests.rs`
- `codex-rs/core/src/config/config_tests.rs`

## Behavioral contract

The pinned Codex tree exposes an `update_plan` checklist, not a general executable workflow graph. Its relevant contract is a small typed state model, strict parsing that rejects unknown fields, explicit status transitions, configuration-gated exposure, and event publication through the session. The model instructions also require coherent progress state rather than multiple simultaneous `in_progress` steps.

## Important invariants

- State and status values have stable serialized spellings.
- Invalid payloads fail at the boundary rather than entering runtime state.
- A state change emits an observable event correlated to the active session/turn.
- The control tool does not pretend that its checklist is an executable task graph.
- Product mode and configuration gates are checked before mutation.
- The successful tool result is compact; detailed state travels through events.

## OpenAI-specific coupling to remove

Codex uses Rust protocol enums, `EventMsg::PlanUpdate`, session/turn services, `ModeKind`, Responses API tool schemas, product-specific tool exposure, and TUI rendering. Super Harness keeps none of those service or UI dependencies. A workflow node receives provider-neutral Python state and may call any application function; the workflow engine itself does not require a model provider.

## Python-native design

`Workflow` validates immutable `Node` and `Edge` declarations as a DAG. `WorkflowEngine` schedules dependency-ready nodes in bounded concurrent batches, applies routes and state updates, and records typed `NodeResult` and `WorkflowEvent` values. Explicit loops live inside a node and require a strict iteration maximum, so ordinary graph cycles remain invalid. Retry requires an explicit idempotency declaration. `WorkflowRun` is versioned JSON and `JSONWorkflowStore` atomically replaces checkpoints after stable batches.

## Differences/intentional extensions

- Adds executable sequence, fan-out/join, predicate/route branches, retry, and bounded loop semantics absent from Codex's checklist tool.
- Adds function, tool, agent, router, subworkflow, transform, and gate node labels; Phase 10 connects agent and subworkflow execution helpers.
- Uses application functions and Python awaitables instead of an OpenAI-specific control tool.
- Adds failure/interruption state and replay-safe resume from completed node checkpoints.
- Adds a local atomic JSON store; durable multi-process orchestration remains an application concern.
- Treats deterministic workflow execution as `Real E2E=N/A` because the complete product boundary is in-process; filesystem checkpoint behavior is covered as integration evidence.

## Tests to reproduce behavior

- Execute a three-node sequence with state and prior result access.
- Prove three branches overlap, then join only after all active inputs finish.
- Select boolean and named router branches, skip inactive nodes, and emit `route.selected`.
- Retry a transient failure with backoff only after `idempotent=True`.
- Terminate a loop normally and fail at its strict maximum.
- Reject duplicate IDs, missing endpoints, self cycles, and multi-node cycles.
- Persist a failed run, reload JSON, resume without replaying completed nodes, and finish.
- Cancel a running node, persist interruption, and resume it.
- Normalize async timeout as node/workflow failure and notify an async event listener.
