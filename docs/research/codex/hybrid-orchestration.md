# Codex Research: Hybrid Orchestration

## Codex files inspected

- `codex-rs/core/src/session/multi_agents.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/spawn.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/wait.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/send_input.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/resume_agent.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/close_agent.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/interrupt_agent.rs`
- `codex-rs/core/src/tools/handlers/plan.rs`

## Codex tests inspected

- `codex-rs/core/src/tools/handlers/multi_agents_tests.rs`
- `codex-rs/core/tests/suite/multi_agent_resume.rs`
- `codex-rs/core/tests/suite/subagent_notifications.rs`
- `codex-rs/core/tests/suite/tool_harness.rs`
- `codex-rs/app-server/tests/suite/v2/multi_agent_v2_developer_instructions.rs`

## Behavioral contract

The pinned Codex runtime supplies an autonomous parent/child Agent tree with spawn, wait, message, resume, interrupt, and close operations. Its separate plan surface is an observable checklist, not an executable workflow or a bridge between deterministic and autonomous execution. The reusable hybrid contract is therefore the Agent lifecycle itself: independent child threads, bounded delegation, selective event-driven joins, inspectable ancestry/results, and subtree cancellation.

## Important invariants

- A workflow-owned Agent still uses a distinct Agent/Thread and the normal model Tool loop.
- A child Agent may autonomously spawn descendants; the workflow node must join or cancel that subtree.
- Agent failure, timeout, cancellation, and budget exhaustion cannot be reported as node success.
- Parent workflow/node/run IDs remain attached to forwarded Agent lifecycle observations.
- Cancelling a workflow node propagates into the Agent subtree before the node becomes interrupted.
- Nested workflow events retain the child workflow/run/node identity under the parent node correlation.
- Resume keeps already completed child workflow nodes when a durable child checkpoint exists.

## OpenAI-specific coupling to remove

Codex couples collaboration to Rust session services, product Agent roles, model catalogs, executor environments, SessionSource, application notifications, and task paths. Super Harness reuses its provider-neutral `AgentManager`, Python `WorkflowEngine`, ordinary `AgentFactory`, and JSON-safe events. No OpenAI service, wire protocol, model, or UI state is required.

## Python-native design

`AutonomousAgentNode` is an async workflow handler. It spawns through an existing `AgentManager`, waits for the child and discovered descendants, converts the terminal Agent result into a node value/state update, and forwards redacted lifecycle metadata through `WorkflowContext.emit`. Cancellation calls `AgentManager.cancel(child_id)` before propagating.

`SubworkflowNode` derives a stable child run ID from the parent run/node. It starts a nested engine or loads and resumes its JSON checkpoint, forwards only new child events, and converts the completed child output to the parent node result. Parent task cancellation reaches the nested engine, which persists interruption before re-raising.

## Differences/intentional extensions

- Adds executable hybrid nodes absent from the pinned Codex tree.
- Uses deterministic parent workflow checkpoints and optional child JSON checkpoints.
- Forwards correlation metadata rather than child token/text payloads, avoiding accidental secret or context leakage.
- Treats any non-completed descendant as a node failure and cancels active descendants after a wait timeout.
- Cross-process Agent-tree persistence remains outside Phase 10; subworkflow recovery is durable, while autonomous Agent-node recovery is retained-process only.

## Tests to reproduce behavior

- Run an autonomous Agent between deterministic prepare/finalize nodes and inspect correlated Agent events.
- Run a durable nested workflow and observe child workflow/run/node events under the parent node.
- Let a workflow Agent use real collaboration Tools to spawn two specialists, wait, and aggregate.
- Cancel the parent workflow and prove the Agent child becomes cancelled without an orphan task.
- Cancel a nested workflow and prove both parent and child checkpoints become interrupted.
- Fail a child workflow, resume the parent, and prove its completed child node is not replayed.
