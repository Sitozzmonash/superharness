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
