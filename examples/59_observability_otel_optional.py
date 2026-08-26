"""Export a completed Super Harness span through an OTEL-compatible tracer."""

from datetime import UTC, datetime, timedelta
from typing import Any

from super_harness import OpenTelemetryExporter, SpanStatus, TraceSpan


class DemoSpan:
    def set_attribute(self, name: str, value: Any) -> None:
        print("attribute", name, value)

    def end(self, *, end_time: int) -> None:
        print("ended", end_time)


class DemoTracer:
    def start_span(self, name: str, **kwargs: Any) -> DemoSpan:
        print("started", name, kwargs["start_time"])
        return DemoSpan()


started = datetime.now(UTC)
span = TraceSpan(
    "demo",
    "workflow",
    started_at=started,
    completed_at=started + timedelta(milliseconds=5),
    status=SpanStatus.OK,
)
OpenTelemetryExporter(tracer=DemoTracer()).export_span(span)

# In production, install `super-harness[otel]` and omit `tracer=` to use the
# process OpenTelemetry provider configured by your application.
