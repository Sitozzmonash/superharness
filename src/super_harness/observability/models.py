"""Provider-neutral logs, spans, and metric snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(UTC)


def _mapping() -> Mapping[str, Any]:
    return {}


class SpanStatus(StrEnum):
    RUNNING = "running"
    OK = "ok"
    ERROR = "error"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class StructuredLogRecord:
    level: str
    event: str
    timestamp: datetime = field(default_factory=_now)
    trace_id: str | None = None
    span_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    agent_id: str | None = None
    workflow_run_id: str | None = None
    node_id: str | None = None
    tool_call_id: str | None = None
    duration_ms: float | None = None
    provider: str | None = None
    model: str | None = None
    tool: str | None = None
    status: str | None = None
    error_class: str | None = None
    details: Mapping[str, Any] = field(default_factory=_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", MappingProxyType(dict(self.details)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "event": self.event,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "agent_id": self.agent_id,
            "workflow_run_id": self.workflow_run_id,
            "node_id": self.node_id,
            "tool_call_id": self.tool_call_id,
            "duration_ms": self.duration_ms,
            "provider": self.provider,
            "model": self.model,
            "tool": self.tool,
            "status": self.status,
            "error_class": self.error_class,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class TraceSpan:
    name: str
    category: str
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid4().hex[:16])
    parent_span_id: str | None = None
    started_at: datetime = field(default_factory=_now)
    completed_at: datetime | None = None
    status: SpanStatus = SpanStatus.RUNNING
    attributes: Mapping[str, Any] = field(default_factory=_mapping)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    @property
    def duration_ms(self) -> float | None:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds() * 1000


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    counters: Mapping[str, float]
    gauges: Mapping[str, float]
    histograms: Mapping[str, tuple[float, ...]]
    estimated_cost_usd: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "counters", MappingProxyType(dict(self.counters)))
        object.__setattr__(self, "gauges", MappingProxyType(dict(self.gauges)))
        object.__setattr__(self, "histograms", MappingProxyType(dict(self.histograms)))
