# Phase 10 Plan: Hybrid Orchestration

1. Reconcile pinned Codex autonomous lifecycle semantics with the Phase 9 deterministic workflow and event/checkpoint contracts.
2. Add an autonomous Agent node that can itself use collaboration Tools, joins descendants, returns bounded output, and rejects non-completed terminal states.
3. Add a subworkflow node with stable child run IDs, optional durable checkpoint resume, state/output propagation, and new-event-only forwarding.
4. Propagate parent cancellation into Agent subtrees and nested engines while retaining interrupted checkpoints and correlated observations.
5. Test Agent, subworkflow, specialist-team, cancellation, failure, and resume boundaries; add four runnable examples.
6. Update research, user/API/internals/compatibility documentation and the matrix, run all gates, commit, and push.
