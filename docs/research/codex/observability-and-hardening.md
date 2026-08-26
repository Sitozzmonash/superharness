# Codex Research: Observability and Hardening

## Codex files inspected

- `codex-rs/otel/README.md`
- `codex-rs/otel/src/events/shared.rs`
- `codex-rs/otel/src/trace_context.rs`
- `codex-rs/otel/src/metrics/client.rs`
- `codex-rs/otel/src/metrics/names.rs`
- `codex-rs/core/src/config/otel.rs`
- `codex-rs/utils/redacted-string/src/lib.rs`
- `codex-rs/app-server/src/request_processors/thread_resume_redaction.rs`

## Codex tests inspected

- `codex-rs/otel/tests/suite/timing.rs`
- `codex-rs/otel/tests/suite/snapshot.rs`
- `codex-rs/otel/tests/suite/validation.rs`
- `codex-rs/otel/tests/suite/otlp_http_loopback.rs`
- `codex-rs/core/tests/suite/otel.rs`
- `codex-rs/app-server/tests/suite/v2/otel.rs`
- `codex-rs/otel/src/tool_result_tests.rs`

## Behavioral contract

Codex separates session/business events, trace-safe events, metrics, trace context, and exporter lifecycle. Telemetry attaches stable correlation metadata, validates metric names/tags, records duration with explicit units, supports in-memory snapshots for assertions, makes exporters optional, and shuts them down explicitly. Sensitive values use redacted wrappers; trace-safe output is narrower than log output.

## Important invariants

- Logging, tracing, and metrics consume structured lifecycle state rather than parsing console text.
- Trace/log payloads differ when content is unsafe for broad export.
- IDs, provider/model/tool, status, duration, and error class remain available after content removal.
- Metric names and values are validated; counters cannot decrease.
- Cost is an estimate from an explicit price table, not a provider billing claim.
- Exporters are optional and flush/shutdown explicitly.
- Export failure is fail-open by default and observable; strict export is opt-in.
- Secrets, bearer tokens, credentials, prompts, model text, tool arguments/results, and image bodies do not enter default telemetry.

## OpenAI-specific coupling to remove

Codex telemetry includes conversation/account/auth/session-source fields, Rust tracing targets, Statsig defaults, Codex model slugs, internal event names, and OTLP configuration owned by the CLI. Super Harness uses provider-neutral runtime IDs, application-owned prices/exporter configuration, Python event observers, and no account identity. OpenTelemetry imports are lazy and optional.

## Python-native design

`Observability.observe` normalizes `Event`, `AgentEvent`, and `WorkflowEvent` values. `SecretRedactor` performs bounded recursive masking before `StructuredLogger` writes console or JSONL. `TraceRecorder` correlates event pairs into an in-memory tree. `MetricsRegistry` stores thread-safe counters, gauges, raw duration observations, token totals, retries, errors, active Agents, and estimated USD cost. `OpenTelemetryExporter` exports completed spans through an injected or lazily loaded tracer.

Agent passes the observer to every Thread; AgentManager and WorkflowEngine accept the observer method as their event listener. Search, RAG, vision, and MCP emit content-free start/completed/failed boundary events with unique operation IDs. Text deltas and payload content are omitted by default.

## Differences/intentional extensions

- Uses a small observer protocol instead of Rust tracing subscribers.
- Keeps raw histogram samples for dependency-free local inspection rather than implementing an aggregation backend.
- Does not install a global OTEL provider; the application owns provider/exporter configuration.
- Adds bounded recursive redaction for nested Python mappings, dataclasses, exceptions, cycles, and application secrets.
- Adds strict JSON/tool identifier validation as a runtime hardening boundary.
- W3C trace-header propagation is deferred; trace IDs are local correlation IDs in Phase 11.

## Tests to reproduce behavior

- Produce console and JSONL records with stable IDs, duration, status, and redacted details.
- Prove configured values, secret fields, bearer tokens, known token shapes, wrappers, cycles, and deep containers do not leak.
- Build Thread/turn/model, workflow/node, Agent, RAG, and MCP observations and trace spans.
- Record input/output/total tokens, latency, errors, retries, active Agents, and explicit-table cost.
- Export a completed span through an injected OTEL tracer without importing the optional dependency.
- Propagate model failure to a failed span and redacted error log.
- Reject malicious tool names, control-character call IDs, cyclic/deep/non-JSON schemas, and non-finite values.
- Run 800 thread-concurrent JSONL writes and 500 async event observations without record loss.
