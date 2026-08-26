"""In-memory event-correlated trace tree."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from .models import SpanStatus, TraceSpan


class TraceRecorder:
    """Build hierarchical spans from normalized lifecycle events."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._spans: list[TraceSpan] = []
        self._active: dict[tuple[str, ...], TraceSpan] = {}
        self._roots: dict[tuple[str, str], TraceSpan] = {}

    def observe(
        self,
        *,
        event_type: str,
        timestamp: datetime,
        identifiers: Mapping[str, str | None],
        attributes: Mapping[str, Any],
    ) -> TraceSpan | None:
        phase = _phase(event_type)
        if phase is None:
            return None
        category = event_type.split(".", 1)[0]
        key = _span_key(category, identifiers, attributes)
        with self._lock:
            if phase == "started":
                parent = self._parent(category, identifiers, timestamp)
                trace_id = parent.trace_id if parent is not None else uuid4().hex
                span = TraceSpan(
                    event_type.removesuffix(".started"),
                    category,
                    trace_id,
                    parent_span_id=parent.span_id if parent is not None else None,
                    started_at=timestamp,
                    attributes=attributes,
                )
                self._active[key] = span
                self._spans.append(span)
                return span
            span = self._active.pop(key, None)
            if span is None:
                parent = self._parent(category, identifiers, timestamp)
                span = TraceSpan(
                    event_type.rsplit(".", 1)[0],
                    category,
                    parent.trace_id if parent is not None else uuid4().hex,
                    parent_span_id=parent.span_id if parent is not None else None,
                    started_at=timestamp,
                    attributes=attributes,
                )
                self._spans.append(span)
            status = {
                "completed": SpanStatus.OK,
                "failed": SpanStatus.ERROR,
                "cancelled": SpanStatus.INTERRUPTED,
                "interrupted": SpanStatus.INTERRUPTED,
            }[phase]
            finished = replace(
                span,
                completed_at=timestamp,
                status=status,
                attributes={**span.attributes, **attributes},
            )
            self._replace(span, finished)
            return finished

    def spans(self, *, trace_id: str | None = None) -> tuple[TraceSpan, ...]:
        with self._lock:
            return tuple(
                span for span in self._spans if trace_id is None or span.trace_id == trace_id
            )

    def tree(self, trace_id: str) -> str:
        spans = self.spans(trace_id=trace_id)
        children: dict[str | None, list[TraceSpan]] = {}
        for span in spans:
            children.setdefault(span.parent_span_id, []).append(span)
        lines: list[str] = []

        def render(parent_id: str | None, depth: int) -> None:
            for span in children.get(parent_id, []):
                duration = f" {span.duration_ms:.1f}ms" if span.duration_ms is not None else ""
                lines.append(f"{'  ' * depth}{span.name} [{span.status.value}]{duration}")
                render(span.span_id, depth + 1)

        render(None, 0)
        return "\n".join(lines)

    def _parent(
        self,
        category: str,
        identifiers: Mapping[str, str | None],
        timestamp: datetime,
    ) -> TraceSpan | None:
        if category == "turn" and identifiers.get("thread_id"):
            return self._root("thread", str(identifiers["thread_id"]), timestamp)
        if category in {"model", "tool", "compaction"} and identifiers.get("turn_id"):
            return self._active.get(("turn", str(identifiers["turn_id"]))) or self._root(
                "thread", str(identifiers.get("thread_id") or identifiers["turn_id"]), timestamp
            )
        if category == "node" and identifiers.get("workflow_run_id"):
            run_id = str(identifiers["workflow_run_id"])
            return self._active.get(("workflow", run_id, "None")) or self._root(
                "workflow", run_id, timestamp
            )
        if category == "agent" and identifiers.get("parent_agent_id"):
            return self._active.get(("agent", str(identifiers["parent_agent_id"])))
        return None

    def _root(self, category: str, identity: str, timestamp: datetime) -> TraceSpan:
        key = (category, identity)
        root = self._roots.get(key)
        if root is None:
            root = TraceSpan(category, category, started_at=timestamp, attributes={"id": identity})
            self._roots[key] = root
            self._spans.append(root)
        return root

    def _replace(self, old: TraceSpan, new: TraceSpan) -> None:
        index = self._spans.index(old)
        self._spans[index] = new


def _phase(event_type: str) -> str | None:
    suffix = event_type.rsplit(".", 1)[-1]
    terminal = {"started", "completed", "failed", "cancelled", "interrupted"}
    return suffix if suffix in terminal else None


def _span_key(
    category: str,
    identifiers: Mapping[str, str | None],
    attributes: Mapping[str, Any],
) -> tuple[str, ...]:
    if category == "turn":
        return (category, str(identifiers.get("turn_id")))
    if category == "model":
        return (category, str(identifiers.get("turn_id")), str(attributes.get("step", 0)))
    if category == "tool":
        return (category, str(identifiers.get("tool_call_id")))
    if category == "agent":
        return (category, str(identifiers.get("agent_id")))
    if category in {"workflow", "node"}:
        return (
            category,
            str(identifiers.get("workflow_run_id")),
            str(identifiers.get("node_id")),
        )
    if category in {"mcp", "rag", "search", "vision"}:
        return (category, str(attributes.get("operation_id")))
    return (category, str(identifiers.get("thread_id") or identifiers.get("workflow_run_id")))
