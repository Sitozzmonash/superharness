# Coding Standards

## 1. Style

- Use `ruff` for lint/format or a documented equivalent.
- Use `pyright` or `mypy` for static typing.
- Public APIs must have type annotations.
- Prefer explicit names over abbreviations.
- Keep functions focused.
- Avoid deep inheritance hierarchies.

## 2. Async

- Network I/O: async.
- Subprocesses: async subprocess APIs.
- Never call blocking SDK functions on event loop without isolation.
- Propagate cancellation.
- Use structured concurrency for child tasks where practical.

## 3. Data models

Use immutable/frozen models for events where possible.

Avoid passing unvalidated raw provider dictionaries beyond adapter boundaries.

Normalize provider responses immediately.

## 4. Interfaces

Provider/backend interfaces should be small:
- `ModelProvider`
- `VisionProvider` or capability on ModelProvider
- `WebSearchProvider`
- `RAGProvider`
- `PersistenceBackend`
- `SandboxBackend`
- `ObservabilityExporter`

Do not make one mega-interface.

## 5. Dependencies

Each dependency requires a reason. Prefer standard library + small proven libraries.

Potential justified dependencies:
- `httpx`
- `pydantic` if used consistently
- `typer`/`click` for CLI
- MCP official Python SDK
- `opentelemetry-*` optional extras
- testing tools

Use optional extras for heavy integrations.

## 6. Exceptions

Do not hide errors. Wrap provider-specific errors into typed framework errors with original cause.

## 7. Retries

Retry only transient failures. Do not blindly retry:
- validation errors;
- approval denied;
- auth failures;
- deterministic tool bugs.

Honor cancellation during backoff.

## 8. Logging

Structured, redacted. No full prompt/tool payload by default in production logging.

## 9. Tests

Prefer deterministic tests. Freeze external fixture revisions. Isolate tests from user's real filesystem except explicit sandbox temp dirs.

## 10. API stability

Before 1.0, changes are allowed but documented. From the first public release, use semantic versioning and deprecation periods for public APIs.
