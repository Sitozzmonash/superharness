"""Optional OpenTelemetry span exporter with no mandatory OTEL dependency."""

from __future__ import annotations

import importlib
from typing import Any

from super_harness.exceptions import ConfigError

from .models import SpanStatus, TraceSpan


class OpenTelemetryExporter:
    """Export completed framework spans through an injected or lazily loaded OTEL tracer."""

    def __init__(self, service_name: str = "super-harness", *, tracer: Any | None = None) -> None:
        if not service_name.strip():
            raise ValueError("OTEL service name must be non-empty")
        self.service_name = service_name
        self._tracer = tracer

    def export_span(self, span: TraceSpan) -> None:
        if span.completed_at is None:
            return
        tracer = self._tracer or self._load_tracer()
        otel_span = tracer.start_span(
            span.name,
            start_time=int(span.started_at.timestamp() * 1_000_000_000),
            attributes={
                "super_harness.category": span.category,
                "super_harness.trace_id": span.trace_id,
                "super_harness.span_id": span.span_id,
                **{key: _otel_value(value) for key, value in span.attributes.items()},
            },
        )
        if span.status is SpanStatus.ERROR:
            otel_span.set_attribute("error.type", str(span.attributes.get("error_class", "error")))
        otel_span.set_attribute("super_harness.status", span.status.value)
        otel_span.end(end_time=int(span.completed_at.timestamp() * 1_000_000_000))

    def _load_tracer(self) -> Any:
        try:
            trace = importlib.import_module("opentelemetry.trace")
        except ImportError as error:
            raise ConfigError(
                "OpenTelemetry is optional; install super-harness[otel] before enabling export"
            ) from error
        self._tracer = trace.get_tracer(self.service_name)
        return self._tracer


def _otel_value(value: object) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)
