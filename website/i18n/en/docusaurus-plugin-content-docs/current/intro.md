---
id: intro
title: Super Harness
slug: /
---

Super Harness is a Python-native, Codex-inspired, provider-agnostic Agent Runtime for coding,
research, enterprise knowledge, multimodal, automation, and multi-agent applications.

:::info Development status

Development is complete through Phase 13 of the 14-phase route as a release candidate.
External-provider E2Es remain credential gated and are never reported as passing when their
credential is absent; V1 is intentionally untagged until every release gate has evidence.

:::

The project keeps OpenAI optional, provides China-ready provider abstractions, treats RAG as an
external retrieval-service contract, and supports autonomous, deterministic, and hybrid orchestration.

## Documentation deployment

The public site is built and deployed from `website/` by GitHub Actions. Deployment happens only
after the production documentation build succeeds; the release-status page distinguishes local
validation from externally verified release evidence.
