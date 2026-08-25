# Phase 9 Plan: Workflow Engine

1. Study the pinned Codex plan state, strict parsing, event, configuration, and test contracts while recording the absence of a generic DAG runtime.
2. Define typed Workflow, Node, Edge, state, run, result, status, retry, output, context, and event values.
3. Implement bounded dependency-batch scheduling for sequence, fan-out/join, conditions, routing, failure, timeout, cancellation, and observability.
4. Reject implicit cycles, keep loops explicit and bounded, and require idempotency before policy-driven retries.
5. Add versioned JSON snapshots, atomic checkpoint storage, and completed-node-preserving resume after failure or interruption.
6. Run targeted and full gates, add five runnable examples, update user/API/internals/compatibility docs and the matrix, then commit and push.
