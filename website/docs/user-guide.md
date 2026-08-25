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
