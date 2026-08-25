# Codex Research: Autonomous Multi-Agent

## Codex files inspected

- `codex-rs/core/src/session/multi_agents.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_common.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/spawn.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/send_input.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/wait.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/resume_agent.rs`
- `codex-rs/core/src/tools/handlers/multi_agents/close_agent.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_v2/interrupt_agent.rs`

## Codex tests inspected

- `codex-rs/core/src/tools/handlers/multi_agents_tests.rs`
- `codex-rs/core/src/tools/handlers/multi_agents_spec_tests.rs`
- `codex-rs/core/tests/suite/multi_agent_resume.rs`
- `codex-rs/core/tests/suite/subagent_notifications.rs`
- `codex-rs/core/tests/suite/guardian_subagent_authorization.rs`
- `codex-rs/app-server/tests/suite/v2/multi_agent_v2_developer_instructions.rs`

## Behavioral contract

Autonomous orchestration exposes model-callable spawn, message, wait, resume, interrupt, and close operations over a live parent/child Agent tree. Children execute concurrently, may spawn descendants, retain distinct threads/configuration, inherit only requested context, and report concise terminal results. Wait is selective and event driven; cancellation and close cascade through subtrees.

## Important invariants

- Agent IDs, parent IDs, root/child thread IDs, role, status, provider, depth, timestamps, timeout, budgets, and results remain inspectable.
- Spawn validates non-empty tasks, active/total/depth/time/token limits, and Agent factory failure before starting work.
- Full context inheritance is explicit; minimal is the default and selected inheritance requires named sources.
- Collaboration tools use the same tool validation/timeout/event loop as other model tools.
- Child deltas are suppressed by default; parents receive bounded results and aggregated lifecycle events.
- Wait uses conditions rather than polling and can target one subset or all selected children.
- Interrupt differs from cancellation; parent/subtree cancellation propagates deterministically.
- Hook failures cannot orphan a pending child or prevent wait notification.
- Usage is accumulated across every model step in a child turn before enforcing budgets.

## OpenAI-specific coupling to remove

Codex orchestration depends on Rust ThreadManager services, model catalog presets, reasoning effort, SessionSource/AgentPath, product-specific collaboration modes, executor environments, and application notifications. Super Harness uses an application-supplied `AgentFactory`, neutral context fragments, normalized Usage, normal Tool values, and in-memory typed state. Provider/model/sandbox choices are made by the factory without OpenAI services.

## Python-native design

`AgentManager` owns `_ManagedAgent` tasks and immutable `AgentSnapshot`, `AgentResult`, and `AgentEvent` views. `spawn_agent` calls a factory with a typed `SpawnRequest`, creates a fresh Thread, attaches six collaboration Tools to every participating Agent, emits hooks/events, and runs the child in an `asyncio.Task`. Condition variables implement selective wait and event streaming. Resume reuses durable in-memory Thread history; close retains resumable state.

## Differences/intentional extensions

- Uses UUID identities instead of Codex task paths/nicknames.
- Makes context inheritance a three-value enum and passes inherited fragments through the factory request.
- Adds an explicit per-child token budget and bounded result text.
- Exposes both application-level methods and the same operations as model-callable Tools.
- Defines subagent hook integration directly on the shared HookRegistry.
- Persistence across process restart is deferred to the Phase 10 persistence expansion; Phase 8 resume covers retained in-memory child Threads.

## Tests to reproduce behavior

- Three children execute concurrently; parent selectively waits, waits all, aggregates results, and inspects the trace tree.
- A model requests `spawn_agent` and `wait_agent` through the actual tool loop, then synthesizes a final response.
- Completed/closed children accept queued follow-up input and resume on the same Thread.
- Interrupt one child; cancel a parent and verify descendant propagation.
- Enforce depth, active count, total count, timeout, child/total token budgets, and child failure.
- Verify minimal/selected/full context inheritance and SUBAGENT_START/END hooks.
- Verify hook failure rollback/notification and default suppression of child text deltas.
- Credential-gated real DeepSeek parent/child spawn-wait-aggregate chain.
