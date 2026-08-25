# Phase 1 Status

Date: 2026-08-25

## Outcome

Phase 1 implementation is complete locally except for the mandatory real DeepSeek E2E gate. The provider-neutral protocol, OpenAI-compatible Chat Completions and Responses adapters, DeepSeek defaults, streaming-first Agent runtime, basic in-memory Thread/Turn state, strict structured output, and tool-call normalization are implemented.

The phase remains `PARTIAL`, not `PASS`, because `DEEPSEEK_API_KEY` is not configured and the required external text, stream, JSON, and tool-call test was skipped.

## Acceptance evidence

| Gate | Result | Evidence |
|---|---|---|
| Pinned Codex research | PASS | Two feature research notes cite provider, client, session, protocol, Thread/Turn source and behavioral tests |
| Ruff format | PASS | `src`, `tests`, `tools`, and `examples` formatted |
| Ruff lint | PASS | All checks passed |
| Pyright strict | PASS | 0 errors, 0 warnings |
| Pytest | PARTIAL | 32 passed; one required real DeepSeek E2E skipped for missing credential |
| Unit tests | PASS | Model values, both wire formats, retry/error behavior, runtime state, failure, and cancellation |
| Real local HTTP integration | PASS | `ThreadingHTTPServer` receives non-streaming and SSE requests over TCP; provider and Agent runtime both exercised |
| Wheel build/install | PASS | `uv build --wheel`; isolated Python 3.12 install imported version `0.0.1.dev0` |
| Secret scan | PASS | High-confidence scan passed; no credential value committed |
| Examples | PASS | Three Python examples compile: basic run, streaming, structured output/tool calls |
| Documentation | PASS | User guide, internals, API reference, examples, research, and phase status updated |
| Docusaurus production build | PASS | Client/server bundles compiled and static files generated |
| DeepSeek real E2E | TODO | One credential-gated test skipped because `DEEPSEEK_API_KEY` is absent |

## Public behavior delivered

- `Agent.run/arun/stream/astream` and reusable in-memory `Thread` sessions.
- Explicit Turn lifecycle with UTC timestamps and completed, failed, and cancelled terminal state.
- Immutable provider-neutral request, response, usage, capability, tool, and stream event values.
- Chat Completions and Responses payload/response/SSE normalization.
- Structured JSON available as both original text and read-only `ModelResponse.output_json`.
- Bounded request and stream retries for transport failures, HTTP 429, and HTTP 5xx; other 4xx errors fail immediately.
- Missing credentials fail before transport and error metadata excludes the secret.
- A stream without `[DONE]` or `response.completed` fails rather than being accepted as complete.

## Deliberately deferred by the roadmap

- Tool execution and iterative tool loop: Phase 2.
- Durable Thread persistence, resume/fork/archive, context assembly, compaction, steer, and interrupt: Phase 3.
- Policy-driven provider fallback: later routing/hardening phases.

## Remaining Phase 1 gate

Configure a rotated `DEEPSEEK_API_KEY` outside the repository and run:

```text
python -m pytest -m e2e tests/test_deepseek_e2e.py
```

Only after that external test passes may the relevant Real E2E cells and Phase 1 status be promoted to `PASS`.
