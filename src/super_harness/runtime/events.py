"""Immutable structured events for runtime state and observability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol
from uuid import uuid4


def _new_event_id() -> str:
    return str(uuid4())


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _empty_payload() -> Mapping[str, Any]:
    return {}


class EventObserver(Protocol):
    """Minimal async/sync-compatible observation boundary."""

    def observe(self, event: object) -> object: ...


@dataclass(frozen=True, slots=True)
class Event:
    """Immutable observation emitted by the runtime.

    Payloads are defensively copied and exposed through a read-only mapping.
    Correlation fields are optional so the same base model can represent
    thread, turn, tool, subagent, and workflow events.
    """

    type: str
    event_id: str = field(default_factory=_new_event_id)
    timestamp: datetime = field(default_factory=_utc_now)
    thread_id: str | None = None
    turn_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    workflow_run_id: str | None = None
    node_id: str | None = None
    tool_call_id: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=_empty_payload)

    def __post_init__(self) -> None:
        if not self.type or not self.type.strip():
            raise ValueError("event type must be a non-empty string")
        if self.timestamp.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
