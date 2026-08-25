# Phase 4 Plan: Search, RAG, and Vision

1. Inspect the pinned Codex web-search, image preparation, view-image implementation, and tests; record the provider-neutral contract.
2. Define immutable search, RAG, vision, and trace values plus async provider protocols.
3. Implement Zhipu web search, external HTTP RAG, and GLM-4V adapters with bounded retry, timeout, cancellation, typed errors, and secret-safe diagnostics.
4. Add `KnowledgeRouter`, model-visible tools, and user-role external-data context injection.
5. Build the frozen real HTTP RAG fixture and cover normal, simple/rich, error, timeout, cancellation, auth, chain, and trace behavior.
6. Add credential-gated real Zhipu E2E tests without claiming skipped tests as passes.
7. Complete user guide, internals, API reference, examples, coverage matrix, package gates, commit, and push.
