"""Unified event observer for logging, tracing, metrics, and optional exporters."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from .logging import StructuredLogger
from .metrics import MetricsRegistry
from .models import StructuredLogRecord, TraceSpan
from .redaction import SecretRedactor
from .tracing import TraceRecorder


class TelemetryExporter(Protocol):
    def export_span(self, span: TraceSpan) -> object: ...


@dataclass(frozen=True, slots=True)
class _NormalizedEvent:
    type: str
    timestamp: datetime
    identifiers: Mapping[str, str | None]
    payload: Mapping[str, Any]


class Observability:
    """Consume runtime events without changing their execution semantics."""

    def __init__(
        self,
        *,
        logger: StructuredLogger | None = None,
        tracer: TraceRecorder | None = None,
        metrics: MetricsRegistry | None = None,
        redactor: SecretRedactor | None = None,
        exporters: Sequence[TelemetryExporter] = (),
        include_deltas: bool = False,
        include_content: bool = False,
        strict_export: bool = False,
    ) -> None:
        self.logger = logger or StructuredLogger()
        self.tracer = tracer or TraceRecorder()
        self.metrics = metrics or MetricsRegistry()
        self.redactor = redactor or SecretRedactor()
        self.exporters = tuple(exporters)
        self.include_deltas = include_deltas
        self.include_content = include_content
        self.strict_export = strict_export
        self.export_errors: list[str] = []

    async def observe(self, event: object) -> None:
        normalized = _normalize(event)
        if not self.include_deltas and normalized.type.endswith(".delta"):
            return
        payload = (
            normalized.payload
            if self.include_content
            else _omit_content(normalized.payload)
        )
        safe_payload = cast(Mapping[str, Any], self.redactor.redact(payload))
        completed = self.tracer.observe(
            event_type=normalized.type,
            timestamp=normalized.timestamp,
            identifiers=normalized.identifiers,
            attributes=safe_payload,
        )
        self.metrics.observe(normalized.type, normalized.payload, completed)
        span = completed
        status = normalized.type.rsplit(".", 1)[-1]
        error_class = _error_class(normalized.payload)
        record = StructuredLogRecord(
            _level(normalized.type),
            normalized.type,
            normalized.timestamp,
            trace_id=span.trace_id if span is not None else None,
            span_id=span.span_id if span is not None else None,
            thread_id=normalized.identifiers.get("thread_id"),
            turn_id=normalized.identifiers.get("turn_id"),
            agent_id=normalized.identifiers.get("agent_id"),
            workflow_run_id=normalized.identifiers.get("workflow_run_id"),
            node_id=normalized.identifiers.get("node_id"),
            tool_call_id=normalized.identifiers.get("tool_call_id"),
            duration_ms=span.duration_ms if span is not None else None,
            provider=_optional_string(safe_payload.get("provider")),
            model=_optional_string(safe_payload.get("model")),
            tool=_optional_string(safe_payload.get("name")),
            status=status,
            error_class=error_class,
            details=safe_payload,
        )
        self.logger.log(record)
        if span is not None and span.completed_at is not None:
            for exporter in self.exporters:
                try:
                    outcome = exporter.export_span(span)
                    if inspect.isawaitable(outcome):
                        await cast(Awaitable[object], outcome)
                except Exception as error:
                    message = self.redactor.text(f"{type(error).__name__}: {error}")
                    self.export_errors.append(message)
                    if self.strict_export:
                        raise

    async def aclose(self) -> None:
        for exporter in self.exporters:
            close = getattr(exporter, "shutdown", None) or getattr(exporter, "close", None)
            if close is not None:
                outcome = close()
                if inspect.isawaitable(outcome):
                    await cast(Awaitable[object], outcome)
        self.logger.close()


def _normalize(event: object) -> _NormalizedEvent:
    event_type = getattr(event, "type", None)
    timestamp = getattr(event, "timestamp", None)
    if not isinstance(event_type, str) or not isinstance(timestamp, datetime):
        raise TypeError("observer expects an Event, AgentEvent, or WorkflowEvent")
    payload = getattr(event, "payload", {})
    if not isinstance(payload, Mapping):
        payload = {"value": payload}
    run_id = getattr(event, "workflow_run_id", None) or getattr(event, "run_id", None)
    identifiers = {
        "thread_id": _identifier(event, "thread_id"),
        "turn_id": _identifier(event, "turn_id"),
        "agent_id": _identifier(event, "agent_id"),
        "parent_agent_id": _identifier(event, "parent_agent_id"),
        "workflow_run_id": str(run_id) if run_id is not None else None,
        "node_id": _identifier(event, "node_id"),
        "tool_call_id": _identifier(event, "tool_call_id"),
    }
    return _NormalizedEvent(event_type, timestamp, identifiers, cast(Mapping[str, Any], payload))


def _identifier(event: object, name: str) -> str | None:
    value = getattr(event, name, None)
    return str(value) if value is not None else None


def _level(event_type: str) -> str:
    if event_type.endswith(".failed"):
        return "ERROR"
    if event_type.endswith((".interrupted", ".cancelled", ".retrying")):
        return "WARNING"
    return "INFO"


def _error_class(payload: Mapping[str, Any]) -> str | None:
    for key in ("error_class", "error_type"):
        if payload.get(key) is not None:
            return str(payload[key])
    error = payload.get("error")
    if isinstance(error, BaseException):
        return type(error).__name__
    if isinstance(error, str) and ":" in error:
        return error.split(":", 1)[0]
    return None


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _omit_content(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    content_keys = {
        "arguments",
        "delta",
        "input",
        "instruction",
        "message",
        "request",
        "response",
        "result",
        "tool_calls",
    }
    return {
        str(key): "<omitted>" if str(key).lower() in content_keys else value
        for key, value in payload.items()
    }
