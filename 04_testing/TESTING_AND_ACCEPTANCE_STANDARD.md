# Testing and Acceptance Standard

## 1. Test pyramid

Every feature must use the layers that apply:

### Unit
Pure logic, parsing, validation, policies, state transitions.

### Integration
Real boundaries with local services/processes:
- SQLite
- Docker
- subprocess
- MCP fixture server
- HTTP mock RAG service
- local plugin/skill install

### Real provider E2E
Actual external provider:
- DeepSeek
- Zhipu search
- Zhipu vision
- selected external MCP/Skill compatibility sources

## 2. What does NOT count

- mocking `httpx` and calling that "Web Search E2E";
- returning fixture list directly and calling that "RAG HTTP E2E";
- testing only tool schema generation but not a model-requested tool call;
- loading a SKILL.md string directly but never installing/discovering it;
- starting a subagent object without concurrent execution/wait/cancel tests;
- docs code that is never run.

## 3. Required negative tests

Every external/runtime subsystem must test:
- invalid configuration
- authentication failure where practical
- timeout
- cancellation
- malformed response
- empty response
- transient failure/retry
- non-retryable failure
- concurrency/reentrancy where relevant

## 4. Provider real E2E

Secure environment supplies:
- `DEEPSEEK_API_KEY`
- `ZHIPU_SEARCH_API_KEY`
- `ZHIPU_VISION_API_KEY`

Required DeepSeek tests:
1. simple completion
2. streaming
3. structured output
4. function/tool call
5. multi-turn through local Thread
6. cancellation if provider/runtime can demonstrate it

Required Zhipu search:
1. ordinary query returns source URLs/titles
2. top_k/count
3. recency/domain filter if provider supports
4. agent tool path
5. timeout/error normalization

Required vision:
1. local image
2. image URL if supported
3. image + text task
4. stream if supported
5. model capability error for unsupported input

## 5. RAG HTTP E2E

Use actual HTTP transport to local test service.

Test:
- `list[str]`
- rich documents
- top_n
- auth
- slow
- timeout
- empty
- 500
- malformed
- cancel
- context injection
- final model answer uses retrieved fact

## 5A. MCP ecosystem compatibility

Test against the current MCP generation and pinned real fixtures:
- stdio server;
- current Streamable HTTP server/client behavior;
- no hard dependency on legacy transport sessions;
- cancellation/timeout semantics appropriate to the negotiated protocol version;
- required HTTP routing metadata for `2026-07-28` where SDK exposes it;
- MRTR/input-required path when supported by selected SDK/fixture;
- import common `mcpServers` config;
- install and validate an `.mcpb` fixture;
- resolve metadata from the Official MCP Registry client without making registry availability a runtime prerequisite;
- malformed/untrusted bundle and hash mismatch rejection.

## 6. Multi-agent

Test:
- spawn multiple children concurrently
- parent waits selectively
- child result aggregation
- send additional input
- interrupt child
- cancel parent propagates
- depth limit
- max active count
- child failure
- budget exhausted
- no orphan tasks

## 7. Workflow

Test:
- sequence
- parallel join
- conditional
- router
- loop termination
- max loop guard
- retry/backoff
- node failure
- cancellation
- persistence/resume
- hybrid autonomous node

## 8. Security tests

- path traversal attempt
- secret redaction
- shell denial in restricted mode
- network restriction where backend supports it
- plugin/skill script sandboxing
- RAG/search prompt injection treated as data
- malicious tool name/schema edge cases

## 9. Documentation tests

- docs static build
- broken links fail
- key example snippets sourced/referenced from runnable files where possible
- `examples/` smoke runner
- no secret patterns in docs/examples

## 10. Release evidence

Store a machine-readable release test summary, e.g.:

```text
artifacts/test-reports/release-e2e.json
```

It should include test names/status/provider model IDs/timestamps but no secret values.

A release cannot claim complete provider support without a recorded real E2E PASS for the advertised tested provider.
