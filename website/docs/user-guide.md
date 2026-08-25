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
