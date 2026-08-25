# Architecture Overview

## 1. Layered model

```text
                         Application
                             |
                       Agent / Thread API
                             |
        +--------------------+--------------------+
        |                    |                    |
     Runtime              Context            Orchestration
        |                    |                    |
   Turn engine        Instructions          Autonomous
   Event bus          Memory/RAG            Workflow
   Cancellation       Compaction            Hybrid
        |                    |                    |
        +--------------------+--------------------+
                             |
                       Execution Layer
         +----------+---------+---------+----------+
         |          |         |         |          |
       Tools       MCP     Sandbox   Approval    Hooks
         |
     Search/RAG/Subagent/Built-ins
                             |
                        Provider Layer
             +---------------+----------------+
             |               |                |
          Models          Search          Persistence
        Text/Vision                       Observability
```

## 2. Dependency direction

High-level runtime depends on interfaces, not concrete providers.

Preferred:
```text
AgentRuntime -> ModelProvider Protocol
```

Avoid:
```text
AgentRuntime -> DeepSeek SDK internals
```

Same for search/RAG/sandbox/persistence.

## 3. Suggested Python package layout

```text
src/super_harness/
├─ __init__.py
├─ agent.py
├─ runtime/
│  ├─ engine.py
│  ├─ thread.py
│  ├─ turn.py
│  ├─ context.py
│  ├─ cancellation.py
│  ├─ compaction.py
│  └─ events.py
├─ models/
│  ├─ base.py
│  ├─ capabilities.py
│  ├─ deepseek.py
│  ├─ zhipu.py
│  └─ openai_compatible.py
├─ tools/
│  ├─ base.py
│  ├─ registry.py
│  ├─ executor.py
│  └─ builtin/
├─ sandbox/
├─ approval/
├─ search/
├─ rag/
├─ memory/
├─ instructions/
├─ skills/
├─ mcp/
├─ plugins/
├─ hooks/
├─ orchestration/
│  ├─ autonomous.py
│  ├─ workflow.py
│  ├─ router.py
│  └─ hybrid.py
├─ persistence/
├─ observability/
├─ config/
├─ cli/
└─ exceptions.py
```

Exact filenames may change, but dependency boundaries should remain.

## 4. Core domain objects

Minimum conceptual objects:
- `Agent`
- `Thread`
- `Turn`
- `TurnHandle`
- `ContextSnapshot`
- `Event`
- `ModelRequest`
- `ModelResponse`
- `Tool`
- `ToolCall`
- `ToolResult`
- `RAGDocument`
- `SearchResult`
- `AgentTask`
- `Workflow`
- `WorkflowRun`

Prefer immutable event/history records and mutable runtime coordinators.

## 5. Sync and async APIs

Internals async-first:

```python
result = await agent.arun("...")
async for event in agent.astream("..."):
    ...
```

Optional ergonomic sync wrappers:

```python
result = agent.run("...")
for event in agent.stream("..."):
    ...
```

Sync wrappers must not create nested event-loop problems; document notebook/async environment behavior.

## 6. Error taxonomy

Use structured exceptions:
- `SuperHarnessError`
- `ConfigError`
- `ProviderError`
- `ModelError`
- `ToolError`
- `ToolValidationError`
- `SandboxError`
- `ApprovalDenied`
- `MCPError`
- `RAGError`
- `SearchError`
- `SkillError`
- `PluginError`
- `WorkflowError`
- `CancelledError` (or normalized wrapper)

Errors should carry correlation IDs when available.

## 7. Budgets

Runtime should support configurable budgets:
- max turns
- max tool calls
- max wall time
- model token/cost budget where known
- max subagents
- max subagent depth
- workflow loop limits
- tool output/context size

Budget exhaustion is explicit and observable.
