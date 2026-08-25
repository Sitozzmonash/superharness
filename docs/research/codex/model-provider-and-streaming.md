# Codex research: model providers and streaming

## Codex files inspected

- `codex-rs/model-provider-info/src/lib.rs`
- `codex-rs/model-provider/src/provider.rs`
- `codex-rs/codex-api/src/common.rs`
- `codex-rs/core/src/client_common.rs`
- `codex-rs/core/src/client.rs`
- `codex-rs/protocol/src/models.rs`

## Codex tests inspected

- `codex-rs/core/tests/suite/json_result.rs`
- `codex-rs/core/tests/suite/stream_no_completed.rs`
- `codex-rs/core/tests/suite/responses_lite.rs`
- `codex-rs/core/src/client_tests.rs`

## Behavioral contract

- A provider describes its endpoint, authentication source, wire protocol, capabilities, retry limits, and stream idle timeout.
- Requests carry normalized messages, tools, parallel-tool preference, and an optional strict JSON schema.
- Streaming produces structured lifecycle, delta, item, usage, and terminal events.
- A stream that closes before its terminal completion event is an error and can consume the bounded stream retry budget.
- Authentication errors are explicit. Empty or missing credential environment variables fail before network I/O.
- Dropping or cancelling a stream cancels downstream work.

## Invariants

- Retry counts and timeouts are bounded.
- Authentication failures and invalid requests are not retried.
- Provider response objects do not escape the provider boundary.
- Tool calls preserve provider call IDs and arguments.
- JSON schemas are transmitted without lossy rewriting.
- A terminal completion event is required for successful streaming.

## OpenAI coupling removed

Super Harness does not depend on OpenAI authentication managers, account state, ChatGPT headers, prompt-cache identifiers, or OpenAI SDK response classes. Both Chat Completions and Responses are wire adapters behind one provider-neutral protocol.

## Python design

- `ModelProvider` is an async protocol.
- Immutable request, response, tool-call, usage, capability, and stream-event values form the boundary.
- `OpenAICompatibleProvider` uses `httpx.AsyncClient`, explicit bearer authentication, bounded retry policy, and an SSE parser.
- `DeepSeekProvider` supplies the official base URL, environment variable, and declared capabilities without changing the neutral contract.

## Differences and extensions

- Chat Completions is supported as a first-class wire format because it is broadly available across China-ready OpenAI-compatible services.
- The provider owns its HTTP client lifecycle and may also accept an injected client for deterministic tests.
- Normalized error metadata includes status and provider, but never request credentials.

## Tests to reproduce

- Missing/empty credentials fail before transport.
- Chat Completions and Responses payloads preserve tools and strict schema.
- Text, usage, JSON, and tool calls normalize identically across wire formats.
- SSE text/tool deltas assemble into one response and require an explicit terminal event.
- 429/5xx and transport failures retry within budget; 4xx/auth failures do not.
- Cancellation closes the active HTTP stream.

