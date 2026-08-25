---
title: User Guide
---

## Create an agent

Install with `pip install -e .`, set `DEEPSEEK_API_KEY`, and create the default China-ready provider:

```python
from super_harness import Agent, DeepSeekProvider

agent = Agent(DeepSeekProvider(), instructions="Answer concisely.")
response = agent.run("Hello")
print(response.text)
```

`Agent.run` starts a fresh Thread. Use `thread = agent.thread()` and call `thread.run(...)` repeatedly when later turns should include earlier messages.

## Async and streaming

The runtime is async-native. `arun` returns the final normalized `ModelResponse`; `astream` yields immutable `Event` objects. Text arrives as `model.text.delta`, followed by `model.completed` and `turn.completed`. Do not call sync methods from an active event loop.

## Structured output and tools

Pass a JSON Schema through `output_schema`. Pass function declarations as `ToolDefinition` values. Phase 1 returns normalized `ToolCall` values with call ID, name, parsed arguments, and raw JSON. It does not execute calls until Phase 2.

## Credentials, retries, and errors

Credentials are read from the named environment variable at request time and never stored in events. DeepSeek uses `DEEPSEEK_API_KEY`. Retry budgets are bounded; transport errors, HTTP 429, and HTTP 5xx can retry. Authentication and other HTTP 4xx errors fail immediately as `ModelError`.

## Define and run tools

Use typed parameters; the decorator derives a Pydantic argument model and provider JSON Schema:

```python
from super_harness import Agent, DeepSeekProvider, tool

@tool
def add(left: int, right: int) -> int:
    """Add two integers."""
    return left + right

agent = Agent(DeepSeekProvider(), tools=[add])
print(agent.run("Use add for 20 and 22.").text)
```

The runtime validates arguments, requests approval, executes with a timeout, bounds output, appends the correlated tool result, and asks the model to continue. Tools marked `supports_parallel=True` may run concurrently when one model step requests several of them.

`ApprovalPolicy.full_access()` is the default. Use `deny_all()` or a sync/async callback returning `ApprovalDecision.ALLOW` or `DENY` for application control.

`LocalSandbox` supports `read_only`, `workspace_write`, and `full_access` path policies. It is a developer convenience, not strong OS isolation. Shell and Python subprocess tools therefore require `full_access`; use the later Docker backend for a stronger boundary.

## Durable Threads

Create `SQLiteThreadStore(path)` and pass it to `Agent`. `agent.thread()` persists immediately; `agent.resume(thread_id)` restores the stable ID and neutral history after restart; `agent.fork(thread_id)` creates an independent child with `parent_thread_id`. `thread.archive()` preserves history but blocks new turns.

## Context and AGENTS.md

Pass `ContextFragment` values to `Agent(context=...)`. Fragments retain kind, role, source, priority, and metadata. Passing `cwd=...` discovers one `AGENTS.override.md` or `AGENTS.md` per directory from the nearest `.git` root down to cwd, never above it. The default total limit is 32 KiB.

`thread.debug_context()` returns a redacted snapshot with ordered provenance and size estimates. RAG/memory fragments are treated as data rather than instruction authority.

## Compaction and active turns

`thread.compact(summary=None, retain_messages=8)` replaces an old history prefix with an explicit summary and emits start/completed events. The default extractive summary preserves lines mentioning security, credentials, sandbox, permissions, approval, or denial. Automatic compaction uses `Agent(compaction_threshold_chars=...)`.

`handle = thread.start(input)` starts background execution. Consume `handle.events()`, await `handle.wait()`, call `await handle.steer(instruction)` at a safe checkpoint, or use `handle.cancel()` / `await handle.interrupt()`. A Thread rejects concurrent active turns.
# Search, RAG, and vision

Configure only the providers you need. Search uses `ZHIPU_SEARCH_API_KEY`; vision uses `ZHIPU_VISION_API_KEY`; RAG uses `RAG_BASE_URL` and optional `RAG_API_KEY`.

```python
from super_harness import HTTPRAGProvider, KnowledgeRouter

router = KnowledgeRouter(rag=HTTPRAGProvider())
fragments = await router.rag_context("What is the release policy?", top_n=3)
```

Pass `fragments` to `Agent(..., context=fragments)`, or register `router.tools()` so the model can retrieve on demand. Search/RAG fragments are deliberately user-role external data and cannot override developer or project instructions.

# Memory

Use `WorkingMemory` for bounded thread-local state. `Thread.messages` remains the durable conversation memory when a `SQLiteThreadStore` is configured. For reusable cross-thread facts, use `SQLiteMemoryStore` and `MemoryManager`:

```python
store = SQLiteMemoryStore("memory.sqlite3")
manager = MemoryManager(store)
await manager.consolidate(thread.thread_id, thread.messages)
fragments = await manager.retrieve_context("release preference", current_thread_id=new_thread.thread_id)
```

The default extractor only accepts explicit lines beginning with `Remember:` or `Memory:`. Supply a custom `MemoryExtractor` for application-specific or model-based extraction.

# Agent Skills

Place standard `SKILL.md` packages in a project `.agents/skills/` or `.super-harness/skills/` directory. Discovery loads only names and descriptions; activate a selected Skill to read its instructions, then request supporting files explicitly.

```python
from super_harness import SkillCatalog, SkillInstaller

catalog = SkillCatalog.discover(cwd=".")
instructions = catalog.activate("code-review").instructions
installed = SkillInstaller(".super-harness/skills").install("./my-skill")
```

The installer accepts local paths, HTTPS Git repositories, and GitHub `/tree/<revision>/<subdir>` URLs. It never overwrites an installed Skill, rejects symbolic links and path escapes, and records the resolved commit and install time.

# MCP

Use `MCPClient` as an async context manager. Stdio starts a child process; Streamable HTTP accepts a URL and optional headers. The official SDK performs protocol negotiation.

```python
from super_harness import MCPClient, MCPServerConfig, MCPTransport

config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="https://example.com/mcp")
async with MCPClient(config) as client:
    tools = await client.as_tools()
    resources = await client.list_resources()
```

Use `include_tools` or `exclude_tools` for allow/deny filtering. Common `{ "mcpServers": ... }` JSON is accepted by `import_mcp_servers`. Treat remote tools and resources as untrusted external input and configure a finite timeout.

# Plugins

Plugins are installed but remain disabled until explicit activation. A plugin may bundle Skills, namespaced Tools, MCP definitions, hooks, and passive assets/personas/commands.

```python
from super_harness import HookRegistry, PluginInstaller, PluginManager, ToolRegistry

tools = ToolRegistry()
hooks = HookRegistry()
manager = PluginManager(PluginInstaller(".super-harness/plugins"), tools=tools, hooks=hooks)
manager.install("./plugins/release-tools")
capabilities = manager.enable("release-tools")
```

Disable before update or removal. Installation validates in staging and never imports plugin Python. `enable` is the trust boundary that executes declared `./file.py:symbol` entries.

# Hooks

Register sync or async callbacks by `HookEvent`. Use `HookResult.enrich(...)` only with `allow_modify=True`; eligible pre-action events may return `HookResult.deny(reason)`. Choose `WARN`, `FAIL_OPEN`, or `FAIL_CLOSED` per registration and always set a finite timeout.

Hooks supplement observability and application policy; they do not replace the approval engine or sandbox. `HookTrace` reports source, event, duration, success, warning, and denial.

# Autonomous multi-Agent

Create an `AgentManager` with a root Agent and an `AgentFactory`. The factory receives role, task, instructions, inherited context, timeout, and token budget and must return a separately configured Agent.

```python
from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest

def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=request.instructions, context=request.inherited_context)

manager = AgentManager(Agent(DeepSeekProvider()), factory)
child = await manager.spawn_agent(manager.root_agent_id, "Research the API", role="researcher")
finished = await manager.wait_all([child.agent_id], timeout=300)
```

The manager automatically attaches `spawn_agent`, `send_input`, `wait_agent`, `resume_agent`, `interrupt_agent`, and `close_agent` Tools to root and child Agents. A capable model can therefore delegate dynamically. Use `expose_tools=False` for application-only control.

Minimal context inheritance is the default. `SELECTED` requires source labels; `FULL` includes all parent fragments plus a marked conversation snapshot and should be used deliberately. Configure `MultiAgentLimits` for active/total agents, depth, total tokens/time, default child timeout, and maximum result size.

`wait` returns when any selected child is terminal; `wait_all` joins all selected children. `send_input` steers a running child at its next checkpoint or queues follow-up input for `resume_agent`. `cancel(parent_id)` cascades through descendants; `interrupt_agent` affects one child and records a distinct terminal state.

# Deterministic workflows

Use a `Workflow` when the application—not a model—must control order and branching. Handlers may be synchronous or async and receive an immutable `WorkflowContext` view.

```python
from super_harness import Edge, Node, NodeOutput, Workflow, WorkflowEngine

flow = Workflow(
    "release",
    [
        Node("build", lambda context: NodeOutput("artifact", {"built": True})),
        Node("publish", lambda context: f"published {context.results['build'].value}"),
    ],
    [Edge("build", "publish")],
)
run = await WorkflowEngine().run(flow)
```

For a condition, return a boolean and use route labels `"true"` / `"false"`; for a named router, return `NodeOutput(route="label")`. Several dependency-ready nodes run concurrently and an ordinary multi-input node acts as a join.

Retries require `idempotent=True`. Explicit loops require `loop_until` plus a finite `max_iterations`; graph cycles are always rejected. Configure `JSONWorkflowStore` on the engine to checkpoint stable batches, then call `resume(workflow, store.load(run_id))`. Completed nodes are retained rather than replayed, so handlers should place durable side effects behind completed-node boundaries.
