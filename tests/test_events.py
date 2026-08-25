from __future__ import annotations

from datetime import UTC, datetime

import pytest

from super_harness.runtime.events import Event


def test_event_defensively_copies_payload() -> None:
    original = {"status": "created"}
    event = Event(type="thread.created", payload=original)

    original["status"] = "mutated"

    assert event.payload == {"status": "created"}
    with pytest.raises(TypeError):
        event.payload["status"] = "changed"  # type: ignore[index]


def test_event_has_utc_timestamp_and_unique_identifier() -> None:
    event = Event(type="turn.started")

    assert event.event_id
    assert event.timestamp.tzinfo is UTC


def test_event_rejects_empty_type_and_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        Event(type=" ")
    with pytest.raises(ValueError, match="timezone-aware"):
        Event(type="turn.started", timestamp=datetime(2026, 8, 25))
