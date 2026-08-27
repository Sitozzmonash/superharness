# Pinned Codex Research — Release Cross-Cutting Features

Date: 2026-08-26
Pinned commit: `7c6eb0eef113ddc16ae5b207ac9add364b489798`

## Deferred tools

Codex context snapshots describe deferred tool namespaces without placing every full definition in
the prompt. Remote compaction tests explicitly filter deferred dynamic declarations while retaining
their completed outputs. Super Harness adopts metadata-first discovery plus explicit/search-triggered
loading, while keeping ordinary provider definitions free of unloaded schemas.

## Sandbox

Codex has platform enforcement adapters and a debug-sandbox command that materializes an effective
permission profile before execution. Super Harness retains its documented local policy backend and
adds a separate Docker CLI backend; it does not claim Codex's Seatbelt/Landlock/Windows enforcement.

## Persona and roles

Codex stores personality as typed Thread configuration and renders it through a model-instruction
template. Agent role metadata is distinct from user messages. Super Harness likewise composes a
typed Persona into developer instructions and stable Thread metadata, with explicit provider/tool
scope validation.

## Config and fallback

Codex materializes effective config/profile state before sandbox/runtime construction and refuses
some unsupported explicit fallbacks. Super Harness implements the source-of-truth precedence
directly and makes provider fallback opt-in, typed, observable, cancellation-safe, and disabled
after visible stream output.

## Router

Codex uses typed routing decisions across runtime/tool/app-server boundaries rather than exposing a
generic Python DAG router. Super Harness's generic Router is an intentional framework extension;
workflow `route.selected` semantics and metadata-only observation remain the compatibility anchor.
