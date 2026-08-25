# Codex Research: Search, RAG, and Vision

## Codex files inspected

- `codex-rs/ext/web-search/src/schema.rs`
- `codex-rs/ext/web-search/src/output.rs`
- `codex-rs/ext/web-search/src/tool.rs`
- `codex-rs/core/src/image_preparation.rs`
- `codex-rs/core/src/tools/handlers/view_image.rs`

## Codex tests inspected

- `codex-rs/core/tests/suite/web_search.rs`
- `codex-rs/core/src/image_preparation_tests.rs`
- Inline tests in `ext/web-search/src/output.rs` and `ext/web-search/src/tool.rs`
- Inline tests in `core/src/tools/handlers/view_image.rs`

## Behavioral contract

Search is a parallel-safe model-visible capability with explicit begin/end observability. Its output is plain model input but is marked as external context. Search action details and result metadata are retained for telemetry without treating results as trusted instructions. Image handling validates file boundaries and type, converts bytes to provider input, bounds processing, and omits image bodies from logs.

Super Harness additionally follows the frozen project RAG contract: `POST /retrieve`, optional bearer auth, `query` and `top_n`, simple or rich results, typed errors, timeout, cancellation, retry only for transient failures, and a real HTTP fixture.

## Important invariants

- External search and RAG text has data authority only and is rendered as user-role context.
- Provider credentials and image data never appear in traces or exception details.
- Cancellation propagates without being normalized into an ordinary provider failure.
- Retry is bounded and limited to transport errors and transient HTTP statuses.
- `top_n` affects both the request and normalized result count.
- Local images are read asynchronously, size-bounded, MIME checked, and converted to data URLs.
- Provider response shapes are normalized before entering the runtime.

## OpenAI-specific coupling to remove

Codex search uses OpenAI hosted tool types, Responses API conversation history, Codex turn metadata, and OpenAI model capability catalogs. Super Harness instead defines Python protocols and immutable neutral values. Zhipu endpoint fields are contained entirely inside adapters. RAG has no model-provider dependency. Vision output is a neutral `VisionResult`.

## Python-native design

`WebSearchProvider`, `RAGProvider`, and `VisionProvider` are async protocols. Concrete HTTP adapters use `httpx.AsyncClient`. `KnowledgeRouter` exposes direct calls, external-data context fragments, and ordinary decorated tools. `KnowledgeTrace` is sent through an optional sync or async callback, keeping observability vendor neutral.

## Differences/intentional extensions

- Adds a first-class external RAG protocol and deterministic fixture, which Codex does not provide here.
- Supports Zhipu standalone search and GLM-4V as separate providers.
- Allows vision providers to receive HTTPS URLs when the provider supports them; local files become data URLs.
- Uses one uniform typed error hierarchy and one trace shape across all three capabilities.
- Supports simple string and rich object RAG results.

## Tests to reproduce behavior

- Real local TCP search and vision requests, authorization, request shape, and response normalization.
- Real local RAG retrieval, auth, deterministic ranking, `top_n`, rich normalization, context authority, tool exposure, trace emission, and final Agent answer.
- Simple RAG normalization and malformed-response rejection.
- Transient retry count, real HTTP timeout, cancellation propagation, missing credentials, and redacted diagnostics.
- Credential-gated real Zhipu search freshness and GLM-4V local/URL image tests.
