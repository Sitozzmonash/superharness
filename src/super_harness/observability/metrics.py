"""Thread-safe in-memory metrics and token cost estimation."""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from super_harness.models import Usage

from .models import MetricsSnapshot, TraceSpan

_METRIC_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD price per one million input and output tokens."""

    input_per_million: float
    output_per_million: float
    cached_input_per_million: float | None = None

    def __post_init__(self) -> None:
        if min(self.input_per_million, self.output_per_million) < 0:
            raise ValueError("model token prices cannot be negative")
        if self.cached_input_per_million is not None and self.cached_input_per_million < 0:
            raise ValueError("cached input price cannot be negative")


class CostEstimator:
    """Estimate model usage cost from an explicit, application-owned price table."""

    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self.prices = dict(prices or {})

    def estimate(self, model: str | None, usage: Usage) -> float | None:
        price = self.prices.get(model or "")
        if price is None:
            return None
        return (
            usage.input_tokens * price.input_per_million
            + usage.output_tokens * price.output_per_million
        ) / 1_000_000


class MetricsRegistry:
    """Counters, gauges, raw histogram observations, and estimated model cost."""

    def __init__(self, *, costs: CostEstimator | None = None) -> None:
        self.costs = costs or CostEstimator()
        self._lock = threading.RLock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}
        self._estimated_cost_usd = 0.0

    def counter(self, name: str, increment: float = 1.0) -> None:
        _validate_metric(name)
        if increment < 0:
            raise ValueError("counter increment cannot be negative")
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + increment

    def gauge(self, name: str, value: float) -> None:
        _validate_metric(name)
        with self._lock:
            self._gauges[name] = value

    def gauge_add(self, name: str, increment: float) -> None:
        _validate_metric(name)
        with self._lock:
            self._gauges[name] = self._gauges.get(name, 0.0) + increment

    def histogram(self, name: str, value: float) -> None:
        _validate_metric(name)
        if value < 0:
            raise ValueError("histogram observation cannot be negative")
        with self._lock:
            self._histograms.setdefault(name, []).append(value)

    def observe(
        self,
        event_type: str,
        details: Mapping[str, Any],
        completed_span: TraceSpan | None,
    ) -> None:
        self.counter(f"super_harness.events.{_metric_segment(event_type)}")
        if event_type.endswith(".failed"):
            self.counter("super_harness.errors.total")
        if event_type == "agent.started":
            self.gauge_add("super_harness.agents.active", 1)
        elif event_type in {
            "agent.completed",
            "agent.failed",
            "agent.cancelled",
            "agent.interrupted",
        }:
            self.gauge_add("super_harness.agents.active", -1)
        if event_type == "model.completed":
            usage = details.get("usage")
            if isinstance(usage, Usage):
                self.counter("super_harness.tokens.input", usage.input_tokens)
                self.counter("super_harness.tokens.output", usage.output_tokens)
                self.counter("super_harness.tokens.total", usage.total_tokens)
                estimated = self.costs.estimate(_optional_string(details.get("model")), usage)
                if estimated is not None:
                    with self._lock:
                        self._estimated_cost_usd += estimated
                    self.counter("super_harness.cost.estimated_usd", estimated)
        if event_type == "node.retrying":
            self.counter("super_harness.workflow.retries")
        if completed_span is not None and completed_span.duration_ms is not None:
            self.histogram(
                f"super_harness.duration_ms.{_metric_segment(completed_span.category)}",
                completed_span.duration_ms,
            )

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            return MetricsSnapshot(
                dict(self._counters),
                dict(self._gauges),
                {key: tuple(values) for key, values in self._histograms.items()},
                self._estimated_cost_usd,
            )


def _validate_metric(name: str) -> None:
    if _METRIC_NAME.fullmatch(name) is None:
        raise ValueError(f"invalid metric name: {name!r}")


def _metric_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None
