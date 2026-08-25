---
title: Architecture & Internals
---

Super Harness uses an async-first, layered architecture. High-level runtime components depend on
small provider and backend protocols instead of concrete SDKs. Each major feature will link to the
exact pinned Codex files and tests that informed its behavioral contract.

