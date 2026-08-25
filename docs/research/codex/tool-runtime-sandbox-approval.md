# Codex research: tool runtime, sandbox, and approval

## Codex files inspected

- `codex-rs/tools/src/tool_definition.rs`
- `codex-rs/tools/src/tool_executor.rs`
- `codex-rs/tools/src/tool_output.rs`
- `codex-rs/tools/src/tool_payload.rs`
- `codex-rs/tools/src/tool_spec.rs`
- `codex-rs/tools/src/json_schema.rs`
- `codex-rs/core/src/tools/registry.rs`
- `codex-rs/core/src/tools/router.rs`
- `codex-rs/core/src/tools/orchestrator.rs`
- `codex-rs/core/src/tools/parallel.rs`
- `codex-rs/core/src/tools/sandboxing.rs`
- `codex-rs/core/src/tools/approvals.rs`
- `codex-rs/core/src/tools/handlers/unified_exec.rs`
- `codex-rs/core/src/tools/handlers/shell_spec.rs`

## Codex tests inspected

- `codex-rs/core/src/tools/registry_tests.rs`
- `codex-rs/core/src/tools/router_tests.rs`
- `codex-rs/core/src/tools/approvals_tests.rs`
- `codex-rs/core/src/tools/sandboxing_tests.rs`
- `codex-rs/core/src/tools/handlers/unified_exec_tests.rs`
- `codex-rs/core/tests/suite/tools.rs`
- `codex-rs/tools/src/json_schema_tests.rs`
- `codex-rs/tools/src/tool_definition_tests.rs`

## Behavioral contract

- A tool keeps its name, description, input schema, execution handler, exposure, timeout, and risk metadata together.
- Registry insertion order is stable; duplicate or reserved names are rejected explicitly.
- A model tool call is normalized, resolved, validated, approved, executed under the selected sandbox policy, bounded, and converted into a model-facing result.
- Unknown tools and invalid arguments become explicit tool failures that the model can observe.
- Cancellation aborts active execution; completed execution is not overwritten by a late cancellation.
- Large outputs are deliberately truncated before they re-enter model context, while diagnostics retain truncation metadata.

## Important invariants

- Approval happens before side effects.
- Validation failure never invokes the callable.
- One call ID links model call, events, result, and follow-up message.
- A registry collision never silently changes the active implementation.
- Filesystem paths are resolved and checked against explicit roots before access.
- Local process execution is not described as a strong security boundary.
- Tool failures are data for the model loop; framework/cancellation failures remain typed exceptions.

## OpenAI-specific coupling to remove

Super Harness uses neutral `ToolDefinition`, `ToolCall`, and `ToolResult` values. Registry and execution do not depend on Responses API item classes, OpenAI namespaces, hosted tools, account state, or Codex telemetry types.

## Python-native design

- `@tool` derives a Pydantic argument model and JSON Schema from a typed function signature.
- `ToolRegistry` owns deterministic registration, namespace, enable/disable, lookup, search, and provider definitions.
- `ToolExecutor` composes validation, `ApprovalPolicy`, timeout/cancellation, result normalization, truncation, and events.
- `LocalSandbox` resolves workspace paths and runs subprocesses with explicit cwd/environment and termination on cancellation.
- The Agent runtime repeats model → tool calls → tool results until a final answer or step budget.

## Differences/intentional extensions

- Phase 2 exposes a compact allow/deny/callback approval policy instead of Codex's UI-specific reviewer and guardian layers.
- Python subprocess and shell tools require full-access local policy because path checks cannot constrain arbitrary child-process behavior.
- Lazy/deferred registration metadata is represented now; model-side dynamic tool search is completed in the later ecosystem phase.

## Tests to reproduce behavior

- Decorator schema generation, validation, sync/async callables, and result normalization.
- Duplicate names, namespaces, enable/disable, ordering, and search.
- Approval allow/deny/callback and guarantee of no side effect after denial.
- Timeout and cancellation, including child-process termination.
- Head/tail output truncation metadata.
- Read-only and workspace path escape denial.
- File read/write/search plus shell and Python built-ins.
- Multi-call tool loop with a local provider fixture and credential-gated DeepSeek E2E.

