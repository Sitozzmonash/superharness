# Phase 4 Status

Date: 2026-08-25

## Outcome

Phase 4 is implemented and passes all credential-free acceptance gates. External RAG is `PASS` because its frozen acceptance explicitly permits a real HTTP fixture E2E. Zhipu search and GLM vision remain `PARTIAL` until credential-gated live tests run with `ZHIPU_SEARCH_API_KEY` and `ZHIPU_VISION_API_KEY`.

## Delivered

- Async provider-neutral protocols and immutable values for search, RAG, and vision.
- Zhipu standalone web search adapter and `glm-4v-flash` vision adapter.
- External `HTTPRAGProvider` with simple/rich normalization.
- Retry, timeout, cancellation, typed errors, secret-safe diagnostics, and sync/async trace callbacks.
- `KnowledgeRouter`, external-data context fragments, and parallel-safe model tools.
- Real deterministic RAG HTTP service with auth and failure modes.
- Nine examples: three each for search, RAG, and vision.

## Acceptance evidence

| Gate | Result | Evidence |
|---|---|---|
| Pinned Codex research | PASS | Search schema/tool/output, search tests, image preparation, view-image implementation/tests recorded |
| Ruff / Pyright | PASS | Project lint clean; strict type checking has zero errors |
| Unit/integration | PASS | Real TCP transport, normalization, routing, context, tools, auth, retry, timeout, cancellation, traces |
| RAG fixture E2E | PASS | Known fact retrieved over HTTP, injected as data context, and present in deterministic Agent answer |
| Real Zhipu search | PENDING | Credential-gated; no `ZHIPU_SEARCH_API_KEY` |
| Real GLM vision | PENDING | Credential-gated; no `ZHIPU_VISION_API_KEY` |
| Full pytest suite | PARTIAL | 58 passed; three external-provider tests skipped for absent credentials |
| Secret scan / wheel / docs | PASS | Secret scan clean; isolated wheel imports public knowledge API; Docusaurus production build succeeds |

## Security boundary

Search and RAG results are always user-role data fragments, never developer/system authority. Authorization values and base64 image bodies are absent from traces and normalized exception details.
