---
title: API 参考
---

## Agent

- `Agent(provider, *, instructions=None)`
- `run/arun(input, *, tools=(), output_schema=None) -> ModelResponse`
- `stream/astream(input, *, tools=(), output_schema=None) -> Event iterator`
- `thread() -> Thread`
- `aclose()`

## Thread 与 Turn

`Thread` 提供相同的 run 和 stream 方法，同时保留有序的 `messages` 和 `turns`。`TurnStatus` 包括 pending、running、waiting-tool、completed、failed、interrupted 和 cancelled。

## Providers

`ModelProvider` 定义 `name`、`capabilities`、`complete`、`stream` 和 `aclose`。`OpenAICompatibleProvider` 支持 `WireAPI.CHAT_COMPLETIONS` 和 `WireAPI.RESPONSES`。`DeepSeekProvider` 提供 DeepSeek 默认值。

## 规范化值

公共不可变值是 `Message`、`ToolDefinition`、`ToolCall`、`Usage`、`ModelCapabilities`、`ModelRequest`、`ModelResponse` 和 `ModelStreamEvent`。

## 事件与错误

每个 `Event` 都有一个 ID、带时区的时间戳、可选的关联 ID 和只读负载。Provider 失败使用 `ModelError`；公共错误消息和详情排除凭证值。

## Tools

- `@tool(...) -> Tool`：从类型化的同步或异步可调用对象派生参数和 JSON Schema。
- `ToolRegistry`：`register`、`unregister`、`get`、`enable`、`disable`、`list`、`search` 和 `definitions`。
- `ToolExecutor.execute(ToolCall) -> ToolResult`：校验、审批、超时、调用、规范化和截断。
- `ApprovalPolicy`：`full_access`、`deny_all` 或回调策略。
- `LocalSandbox(workspace, mode=...)`：受检查的路径解析和可取消的本地子进程。
- 内置项：`file_read_tool`、`file_write_tool`、`file_search_tool`、`shell_tool`、`python_tool` 和 `basic_builtin_tools`。

`ToolResult` 暴露调用 ID、名称、有界输出、成功与否、截断标志、原始字符数和规范化的错误类型。

## 持久 Thread 与上下文

- `SQLiteThreadStore(path)`：`save`、`load`、`archive`、`ids`、`close` 和上下文管理器支持。
- `Agent.resume(thread_id)` / `Agent.fork(thread_id)`。
- `Thread.archive`、`fork`、`compact`、`debug_context` 和 `start`。
- `ContextFragment`、`ContextKind`、`ContextAssembler`、`ContextDebugSnapshot` 和 `AgentsMdLoader`。
- `ContextSummary`：不可变的摘要 ID、内容、覆盖消息数和 UTC 时间戳。
- `TurnHandle.events`、`wait`、`steer`、`cancel` 和 `interrupt`。
# 知识 API

- `ZhipuWebSearchProvider.search(query, top_n=5) -> SearchResponse`
- `HTTPRAGProvider.retrieve(query, top_n=3) -> tuple[RAGDocument, ...]`
- `ZhipuVisionProvider.analyze(image, prompt) -> VisionResult`
- `KnowledgeRouter.search_context(...)` 和 `rag_context(...)`
- `KnowledgeRouter.tools() -> tuple[Tool, ...]`

Provider 失败会抛出 `SearchError`、`RAGError` 或 `VisionError`。取消以 `asyncio.CancelledError` 传播。

# 记忆 API

- `WorkingMemory(max_items=64)`：`set`、`get`、`delete`、`clear`、`snapshot`、`context`。
- `SQLiteMemoryStore(path)`：异步 `remember`、`get`、`search`、`forget`、`close`。
- `MemoryManager(store, extractor=None, trace_sink=None)`：`consolidate` 和 `retrieve_context`。
- `MemoryCandidate`、`MemoryRecord`、`MemoryMatch`、`MemoryKind` 和 `MemoryTrace` 是 provider 无关的值。

# Skills API

- `parse_skill(path) -> SkillMetadata`
- `activate_skill(metadata) -> ActivatedSkill`
- `SkillCatalog.discover(...)`、`list`、`get` 和 `activate`
- `ActivatedSkill.read_resource(relative_path) -> bytes`
- `SkillInstaller(destination)`：`install`、`update`、`remove`、`list` 和 `info`。

校验和安装失败会抛出 `SkillError`。

# MCP API

- `MCPServerConfig` 和 `MCPTransport.STDIO` / `STREAMABLE_HTTP`
- `MCPClient`：`list_tools`、`call_tool`、`list_resources`、`read_resource`、`list_prompts`、`get_prompt` 和 `as_tools`
- `import_mcp_servers(value) -> tuple[MCPServerConfig, ...]`
- `inspect_mcpb` 和 `install_mcpb`
- `MCPRegistry` 和 `OfficialMCPRegistry`

协议、传输、超时、过滤、注册表和捆绑包失败会抛出 `MCPError`。任务取消永远不会被转换为 `MCPError`。

# Hooks API

- `HookEvent`：session、turn、prompt、model、tool、compaction、subagent 和 error 事件。
- `HookRegistry.register`、`unregister`、`list` 和异步 `dispatch`。
- `HookContext`、`HookResult.enrich`、`HookResult.deny`、`HookOutcome` 和 `HookTrace`。
- `HookFailurePolicy.WARN`、`FAIL_OPEN` 和 `FAIL_CLOSED`。
- `Thread.acompact` 和 `Thread.aclose` 分发异步压缩/session 生命周期钩子。

# 插件 API

- `load_plugin(path) -> PluginManifest`
- `PluginInstaller(destination)`：`install`、`update`、`remove`、`list` 和 `info`。
- `PluginManager`：生命周期方法加上 `enable`、`disable` 和 `capabilities`。
- `InstalledPlugin`、`PluginCapabilities`、`PluginHookSpec` 和 `PluginTrace`。

插件校验、安装、冲突和激活失败会抛出 `PluginError`；钩子 fail-closed 和无效的生命周期操作会抛出 `HookError`。

# 自主多 Agent API

- `AgentManager(root_agent, factory, *, limits=None, hooks=None, include_child_deltas=False, expose_tools=True)`
- `spawn_agent`、`send_input`、`wait`、`wait_all`、`resume_agent`、`interrupt_agent`、`cancel`、`close_agent` 和 `aclose`
- `list_agents`、`get`、`thread`、`results`、`event_history`、异步 `events` 和 `tokens_used`
- `MultiAgentLimits`、`ContextInheritance` 和 `SpawnRequest`
- `AgentStatus`、`AgentSnapshot`、`AgentResult` 和 `AgentEvent`
- `collaboration_tools(parent_agent_id) -> tuple[Tool, ...]`

限制、身份、状态、工厂和生命周期违规会抛出 `MultiAgentError`。子级 provider 错误变成失败的 `AgentResult` 值；调用方取消在调用方边界保持 `asyncio.CancelledError`，并将受影响的子级标记为已取消。

# Workflow API

- `Workflow(workflow_id, nodes, edges=())`：校验唯一的节点 ID、端点和无环图。
- `Node(node_id, handler, kind=..., retry=..., timeout=..., idempotent=..., loop_until=..., max_iterations=...)`。
- `Edge(source, target, route=None, predicate=None)`：普通依赖或一个条件选择器。
- `WorkflowEngine(max_concurrency=8, store=None, event_listener=None)`：异步 `run`、`resume` 和 `cancel`。
- `NodeOutput(value=None, updates={}, route=None)`：原子地发布状态更新和一个可选路由。
- `WorkflowContext`：不可变的输入、状态快照、结果映射、尝试次数和循环迭代视图。
- `WorkflowRun`：`output`、`to_dict`、`to_json`、`from_dict` 和 `from_json`。
- `JSONWorkflowStore(directory)`：原子 `save(run)` 和带版本检查的 `load(run_id)`。
- `RetryPolicy`、`NodeKind`、`NodeStatus`、`WorkflowStatus`、`NodeResult` 和 `WorkflowEvent`。

无效的图/检查点会抛出 `WorkflowError`。节点异常和异步超时变成失败的结果数据。调用方请求的引擎取消返回一个中断的 run；对调用方任务的直接取消仍传播 `asyncio.CancelledError`。

# 混合编排 API

- `agent_node(node_id, manager, task, *, role=..., parent_agent_id=..., instructions=..., inheritance=..., selected_sources=..., timeout=..., token_budget=...) -> Node`。
- `AutonomousAgentNode`：可调用处理器加上用于显式桥接控制的 `cancel(parent_run_id)`。
- `subworkflow_node(node_id, workflow, *, engine=None, input_builder=..., state_builder=None) -> Node`。
- `SubworkflowNode`：可调用处理器加上 `cancel(parent_run_id)`。

Agent 节点返回子级响应文本，并在 `hybrid.<node_id>.*` 状态键下写入其 Agent ID、Thread ID 和 token 数。子工作流节点返回嵌套输出并记录其 workflow/run ID。两者都通过父工作流事件流转发 JSON 安全的关联元数据。

# 可观测性 API

- `Observability(logger=None, tracer=None, metrics=None, redactor=None, exporters=(), include_deltas=False, include_content=False, strict_export=False)` 和异步 `observe(event)` / `aclose()`。
- `StructuredLogger(console=sys.stderr, jsonl=None)`：线程安全的 `log`、`close` 和上下文管理器支持。
- `SecretRedactor(secrets=(), secret_keys=(), custom=(), max_depth=8, max_items=128, max_string_chars=20000)`。
- `TraceRecorder.observe`、`spans(trace_id=None)` 和 `tree(trace_id)`；值使用 `TraceSpan` 和 `SpanStatus`。
- `MetricsRegistry`：`counter`、`gauge`、`gauge_add`、`histogram`、`observe` 和 `snapshot`。
- `CostEstimator({model: ModelPrice(...)})` 和 `MetricsSnapshot`。
- `OpenTelemetryExporter(service_name="super-harness", tracer=None)`：导出已完成的 span；仅在未注入 tracer 时才需要 `super-harness[otel]` 惰性导入。

将 `observer=observability` 传给 `Agent`、`HTTPRAGProvider`、`ZhipuWebSearchProvider`、`ZhipuVisionProvider` 或 `MCPClient`。将 `event_listener=observability.observe` 传给 `AgentManager` 和 `WorkflowEngine`。

# CLI API

- `super_harness.cli.main(argv=None) -> int`：执行显式 `argv`；无参数时保留
  仅版本兼容的 Python 调用。已安装的脚本使用 `cli_entrypoint()`。
- `CLIPaths.resolve(cwd, global_scope=False)`：在不暴露密钥的情况下计算作用域状态。
- `MCPConfigStore`：原子 `list`、`get`、`add`、`import_file` 和 `remove` 操作。
- 退出码 `0` 表示完成；规范化的失败返回 `2` 并写入脱敏的 stderr。

# Phase 13 API

- `Persona`：指令组合、Tool/Skill/记忆作用域、模型校验、子代理角色
  和安全元数据。
- `ConfigResolver.resolve(...) -> ResolvedConfig`；`HarnessConfig`、`ModelConfig`、`VisionConfig`、
  `WebSearchConfig`、`SandboxConfig`、`ApprovalConfig`、`MultiAgentConfig` 和
  `PersistenceConfig` 是冻结的校验模型。
- `SecretProvider`；具体的 `EnvironmentSecretProvider`、`MappingSecretProvider` 和
  `CompositeSecretProvider` 返回遮蔽的 `SecretValue` 对象。
- `ToolRegistry.register_lazy`、`load`、`unregister_lazy`、`deferred` 和 `discover`；
  `LazyTool` 是元数据，`LazyToolLoader` 是延迟工厂边界。
- `Route`、`RouteDecision` 和 `Router.route` / `aroute` 提供类型化规则路由。
- `FallbackPolicy` 和 `FallbackProvider` 提供有序、可观测的 provider 回退。
- `DockerSandbox.build_command`、`describe`、`available`、`run_exec` 和 `run_shell` 提供
  容器后端。

相邻的 Generated Public API 页面由 `super_harness.__all__` 通过
`python tools/generate_api_reference.py` 重建；CI/构建审查检测导出与文档之间的漂移。
