---
title: API Reference
---

## Agent

- `Agent(provider, *, instructions=None)`
- `run/arun(input, *, tools=(), output_schema=None) -> ModelResponse`
- `stream/astream(input, *, tools=(), output_schema=None) -> Event iterator`
- `thread() -> Thread`
- `aclose()`

## Thread and Turn

`Thread` offers the same run and stream methods while retaining ordered `messages` and `turns`. `TurnStatus` includes pending, running, waiting-tool, completed, failed, interrupted, and cancelled.

## Providers

`ModelProvider` defines `name`, `capabilities`, `complete`, `stream`, and `aclose`. `OpenAICompatibleProvider` supports `WireAPI.CHAT_COMPLETIONS` and `WireAPI.RESPONSES`. `DeepSeekProvider` supplies DeepSeek defaults.

## Normalized values

Public immutable values are `Message`, `ToolDefinition`, `ToolCall`, `Usage`, `ModelCapabilities`, `ModelRequest`, `ModelResponse`, and `ModelStreamEvent`.

## Events and errors

Every `Event` has an ID, timezone-aware timestamp, optional correlation IDs, and read-only payload. Provider failures use `ModelError`; public error messages and details exclude credential values.

## Tools

- `@tool(...) -> Tool`: derives arguments and JSON Schema from a typed sync or async callable.
- `ToolRegistry`: `register`, `unregister`, `get`, `enable`, `disable`, `list`, `search`, and `definitions`.
- `ToolExecutor.execute(ToolCall) -> ToolResult`: validation, approval, timeout, invocation, normalization, and truncation.
- `ApprovalPolicy`: `full_access`, `deny_all`, or callback policy.
- `LocalSandbox(workspace, mode=...)`: checked path resolution and cancellable local subprocesses.
- Built-ins: `file_read_tool`, `file_write_tool`, `file_search_tool`, `shell_tool`, `python_tool`, and `basic_builtin_tools`.

`ToolResult` exposes call ID, name, bounded output, success, truncation flag, original character count, and normalized error type.

## Durable Thread and context

- `SQLiteThreadStore(path)`: `save`, `load`, `archive`, `ids`, `close`, and context-manager support.
- `Agent.resume(thread_id)` / `Agent.fork(thread_id)`.
- `Thread.archive`, `fork`, `compact`, `debug_context`, and `start`.
- `ContextFragment`, `ContextKind`, `ContextAssembler`, `ContextDebugSnapshot`, and `AgentsMdLoader`.
- `ContextSummary`: immutable summary ID, content, covered-message count, and UTC timestamp.
- `TurnHandle.events`, `wait`, `steer`, `cancel`, and `interrupt`.
# Knowledge API

- `ZhipuWebSearchProvider.search(query, top_n=5) -> SearchResponse`
- `HTTPRAGProvider.retrieve(query, top_n=3) -> tuple[RAGDocument, ...]`
- `ZhipuVisionProvider.analyze(image, prompt) -> VisionResult`
- `KnowledgeRouter.search_context(...)` and `rag_context(...)`
- `KnowledgeRouter.tools() -> tuple[Tool, ...]`

Provider failures raise `SearchError`, `RAGError`, or `VisionError`. Cancellation propagates as `asyncio.CancelledError`.

# Memory API

- `WorkingMemory(max_items=64)`: `set`, `get`, `delete`, `clear`, `snapshot`, `context`.
- `SQLiteMemoryStore(path)`: async `remember`, `get`, `search`, `forget`, `close`.
- `MemoryManager(store, extractor=None, trace_sink=None)`: `consolidate` and `retrieve_context`.
- `MemoryCandidate`, `MemoryRecord`, `MemoryMatch`, `MemoryKind`, and `MemoryTrace` are provider-neutral values.

# Skills API

- `parse_skill(path) -> SkillMetadata`
- `activate_skill(metadata) -> ActivatedSkill`
- `SkillCatalog.discover(...)`, `list`, `get`, and `activate`
- `ActivatedSkill.read_resource(relative_path) -> bytes`
- `SkillInstaller(destination)`: `install`, `update`, `remove`, `list`, and `info`.

Validation and installation failures raise `SkillError`.

# MCP API

- `MCPServerConfig` and `MCPTransport.STDIO` / `STREAMABLE_HTTP`
- `MCPClient`: `list_tools`, `call_tool`, `list_resources`, `read_resource`, `list_prompts`, `get_prompt`, and `as_tools`
- `import_mcp_servers(value) -> tuple[MCPServerConfig, ...]`
- `inspect_mcpb` and `install_mcpb`
- `MCPRegistry` and `OfficialMCPRegistry`

Protocol, transport, timeout, filtering, registry, and bundle failures raise `MCPError`. Task cancellation is never converted to `MCPError`.

# Hooks API

- `HookEvent`: session, turn, prompt, model, tool, compaction, subagent, and error events.
- `HookRegistry.register`, `unregister`, `list`, and async `dispatch`.
- `HookContext`, `HookResult.enrich`, `HookResult.deny`, `HookOutcome`, and `HookTrace`.
- `HookFailurePolicy.WARN`, `FAIL_OPEN`, and `FAIL_CLOSED`.
- `Thread.acompact` and `Thread.aclose` dispatch async compaction/session lifecycle hooks.

# Plugins API

- `load_plugin(path) -> PluginManifest`
- `PluginInstaller(destination)`: `install`, `update`, `remove`, `list`, and `info`.
- `PluginManager`: lifecycle methods plus `enable`, `disable`, and `capabilities`.
- `InstalledPlugin`, `PluginCapabilities`, `PluginHookSpec`, and `PluginTrace`.

Plugin validation, installation, conflict, and activation failures raise `PluginError`; hook fail-closed and invalid lifecycle actions raise `HookError`.

# Autonomous multi-Agent API

- `AgentManager(root_agent, factory, *, limits=None, hooks=None, include_child_deltas=False, expose_tools=True)`
- `spawn_agent`, `send_input`, `wait`, `wait_all`, `resume_agent`, `interrupt_agent`, `cancel`, `close_agent`, and `aclose`
- `list_agents`, `get`, `thread`, `results`, `event_history`, async `events`, and `tokens_used`
- `MultiAgentLimits`, `ContextInheritance`, and `SpawnRequest`
- `AgentStatus`, `AgentSnapshot`, `AgentResult`, and `AgentEvent`
- `collaboration_tools(parent_agent_id) -> tuple[Tool, ...]`

Limit, identity, state, factory, and lifecycle violations raise `MultiAgentError`. Child provider errors become failed `AgentResult` values; caller cancellation remains `asyncio.CancelledError` at the caller boundary and marks affected children cancelled.

# Workflow API

- `Workflow(workflow_id, nodes, edges=())`: validates unique node IDs, endpoints, and an acyclic graph.
- `Node(node_id, handler, kind=..., retry=..., timeout=..., idempotent=..., loop_until=..., max_iterations=...)`.
- `Edge(source, target, route=None, predicate=None)`: ordinary dependency or one conditional selector.
- `WorkflowEngine(max_concurrency=8, store=None, event_listener=None)`: async `run`, `resume`, and `cancel`.
- `NodeOutput(value=None, updates={}, route=None)`: atomically publishes state updates and an optional route.
- `WorkflowContext`: immutable input, state snapshot, result map, attempt, and loop iteration view.
- `WorkflowRun`: `output`, `to_dict`, `to_json`, `from_dict`, and `from_json`.
- `JSONWorkflowStore(directory)`: atomic `save(run)` and version-checked `load(run_id)`.
- `RetryPolicy`, `NodeKind`, `NodeStatus`, `WorkflowStatus`, `NodeResult`, and `WorkflowEvent`.

Invalid graphs/checkpoints raise `WorkflowError`. Node exceptions and async timeouts become failed result data. A caller-requested engine cancellation returns an interrupted run; direct cancellation of the caller task still propagates `asyncio.CancelledError`.

# Hybrid orchestration API

- `agent_node(node_id, manager, task, *, role=..., parent_agent_id=..., instructions=..., inheritance=..., selected_sources=..., timeout=..., token_budget=...) -> Node`.
- `AutonomousAgentNode`: callable handler plus `cancel(parent_run_id)` for explicit bridge control.
- `subworkflow_node(node_id, workflow, *, engine=None, input_builder=..., state_builder=None) -> Node`.
- `SubworkflowNode`: callable handler plus `cancel(parent_run_id)`.

An Agent node returns the child response text and writes its Agent ID, Thread ID, and token count under `hybrid.<node_id>.*` state keys. A subworkflow node returns the nested output and records its workflow/run IDs. Both forward JSON-safe correlation metadata through the parent workflow event stream.

# Observability API

- `Observability(logger=None, tracer=None, metrics=None, redactor=None, exporters=(), include_deltas=False, include_content=False, strict_export=False)` and async `observe(event)` / `aclose()`.
- `StructuredLogger(console=sys.stderr, jsonl=None)`: thread-safe `log`, `close`, and context-manager support.
- `SecretRedactor(secrets=(), secret_keys=(), custom=(), max_depth=8, max_items=128, max_string_chars=20000)`.
- `TraceRecorder.observe`, `spans(trace_id=None)`, and `tree(trace_id)`; values use `TraceSpan` and `SpanStatus`.
- `MetricsRegistry`: `counter`, `gauge`, `gauge_add`, `histogram`, `observe`, and `snapshot`.
- `CostEstimator({model: ModelPrice(...)})` and `MetricsSnapshot`.
- `OpenTelemetryExporter(service_name="super-harness", tracer=None)`: exports completed spans; lazy import requires `super-harness[otel]` only when no tracer is injected.

Pass `observer=observability` to `Agent`, `HTTPRAGProvider`, `ZhipuWebSearchProvider`, `ZhipuVisionProvider`, or `MCPClient`. Pass `event_listener=observability.observe` to `AgentManager` and `WorkflowEngine`.

# CLI API

- `super_harness.cli.main(argv=None) -> int`: execute explicit `argv`; no arguments retain the
  version-only Python compatibility call. The installed script uses `cli_entrypoint()`.
- `CLIPaths.resolve(cwd, global_scope=False)`: compute scoped state without exposing secrets.
- `MCPConfigStore`: atomic `list`, `get`, `add`, `import_file`, and `remove` operations.
- Exit `0` means completion; normalized failures return `2` and write redacted stderr.
