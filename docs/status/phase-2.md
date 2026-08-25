# Phase 2 Status

Date: 2026-08-25

## Outcome

Phase 2 is implemented and locally verified, but its roadmap gate remains `PARTIAL` because the real DeepSeek tool-loop E2E requires `DEEPSEEK_API_KEY` and was skipped. No external credential value is present in the repository.

Delivered: typed decorator, deterministic registry, validation, approval, timeouts and cancellation, bounded output, local path policy, file/shell/Python built-ins, parallel-safe execution, and a bounded iterative Agent tool loop for both provider wire formats.

## Acceptance evidence

| Gate | Result | Evidence |
|---|---|---|
| Pinned Codex research | PASS | Tool definition/executor/output, registry/router, orchestrator, approvals, sandboxing, parallelism, handlers, and tests recorded in one research note |
| Ruff format/lint | PASS | `src`, `tests`, `tools`, and `examples` clean |
| Pyright strict | PASS | 0 errors, 0 warnings |
| Pytest | PARTIAL | 44 passed; one required DeepSeek E2E skipped for missing credential |
| Tool unit behavior | PASS | Schema, validation, registry conflicts/state/search, approval denial, timeout, truncation, step budget, and concurrency |
| Real local integrations | PASS | TCP model/tool/model loop, file I/O, glob search, shell, Python child process, and cancellation cleanup |
| Wire compatibility | PASS | Chat assistant/tool messages and Responses function-call/output items tested |
| Secret scan | PASS | High-confidence scan passed |
| Local examples | PASS | Approval example denies before invocation; built-in example writes/reads and runs Python |
| Documentation | PASS | User guide, internals, API reference, examples, research, and status updated |
| DeepSeek real tool-loop E2E | TODO | Credential-gated test requires a rotated `DEEPSEEK_API_KEY` |

## Security boundary

`LocalSandbox` checks resolved paths against the configured workspace in restricted modes, applies an environment allowlist, and kills its process group/tree when cancelled. It is explicitly not strong isolation. Shell and Python child processes require `full_access`; Docker isolation remains a later roadmap deliverable.

Custom synchronous tools execute in a worker thread. Python cannot forcibly stop an arbitrary running thread, so timeout/cancellation is cooperative for that category. Async tools and supplied subprocess built-ins receive effective cancellation cleanup.

## Deliberately deferred

- Strong Docker sandbox and resource limits.
- Dynamic lazy tool loading/search across plugin and MCP sources.
- Generic lifecycle hooks around tool use.
- Policy-driven provider fallback.
- Durable Thread state and context controls from Phase 3.

## Remaining Phase 2 gate

Configure a rotated credential outside the repository and run:

```text
python -m pytest -m e2e tests/test_deepseek_e2e.py
```

The test covers text, streaming, strict JSON, and a complete DeepSeek tool call → local execution → final-answer loop. Phase 2 cannot be promoted to `PASS` until it succeeds.
