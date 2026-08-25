"""Immutable values shared by working and long-term memory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4


class MemoryKind(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    SUMMARY = "summary"
    NOTE = "note"


def _empty_metadata() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    content: str
    kind: MemoryKind = MemoryKind.NOTE
    tags: tuple[str, ...] = ()
    importance: float = 0.5
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("memory content must be non-empty")
        if not 0 <= self.importance <= 1:
            raise ValueError("memory importance must be between 0 and 1")
        object.__setattr__(self, "tags", tuple(dict.fromkeys(self.tags)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    content: str
    kind: MemoryKind = MemoryKind.NOTE
    source_thread_id: str | None = None
    tags: tuple[str, ...] = ()
    importance: float = 0.5
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
    memory_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    usage_count: int = 0
    last_accessed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("memory content must be non-empty")
        if not 0 <= self.importance <= 1:
            raise ValueError("memory importance must be between 0 and 1")
        object.__setattr__(self, "tags", tuple(dict.fromkeys(self.tags)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    record: MemoryRecord
    score: float


@dataclass(frozen=True, slots=True)
class MemoryTrace:
    operation: str
    success: bool
    item_count: int = 0
    thread_id: str | None = None
