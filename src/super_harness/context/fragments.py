"""Typed context fragments with authority and provenance."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import Any

from super_harness.models import Message, MessageRole


class ContextKind(StrEnum):
    RUNTIME = "runtime"
    DEVELOPER = "developer"
    PROJECT = "project"
    PERSONA = "persona"
    SKILL = "skill"
    MEMORY = "memory"
    RAG = "rag"
    SUMMARY = "summary"


class ContextPriority(IntEnum):
    RUNTIME = 10
    DEVELOPER = 20
    PROJECT = 40
    PERSONA = 50
    SKILL = 60
    SUMMARY = 70
    MEMORY = 80
    RAG = 90


_PRIORITY = {
    ContextKind.RUNTIME: ContextPriority.RUNTIME,
    ContextKind.DEVELOPER: ContextPriority.DEVELOPER,
    ContextKind.PROJECT: ContextPriority.PROJECT,
    ContextKind.PERSONA: ContextPriority.PERSONA,
    ContextKind.SKILL: ContextPriority.SKILL,
    ContextKind.SUMMARY: ContextPriority.SUMMARY,
    ContextKind.MEMORY: ContextPriority.MEMORY,
    ContextKind.RAG: ContextPriority.RAG,
}


def _empty_metadata() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ContextFragment:
    kind: ContextKind
    content: str
    source: str
    role: MessageRole = MessageRole.USER
    priority: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("context fragment content must be non-empty")
        if not self.source.strip():
            raise ValueError("context fragment source must be non-empty")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def effective_priority(self) -> int:
        return int(self.priority if self.priority is not None else _PRIORITY[self.kind])

    def render(self) -> Message:
        body = (
            f'<context kind="{self.kind.value}" source="{self.source}">\n{self.content}\n</context>'
        )
        return Message(self.role, body)


def _fragment_list() -> list[ContextFragment]:
    return []


@dataclass(slots=True)
class ContextAssembler:
    max_chars: int = 100_000
    fragments: list[ContextFragment] = field(default_factory=_fragment_list)

    def add(self, fragment: ContextFragment) -> None:
        self.fragments.append(fragment)

    def extend(self, fragments: Iterable[ContextFragment]) -> None:
        self.fragments.extend(fragments)

    def ordered(self) -> tuple[ContextFragment, ...]:
        seen: set[tuple[ContextKind, str, str]] = set()
        selected: list[tuple[int, ContextFragment]] = []
        for index, fragment in enumerate(self.fragments):
            key = (fragment.kind, fragment.source, fragment.content)
            if key in seen:
                continue
            seen.add(key)
            selected.append((index, fragment))
        selected.sort(key=lambda item: (item[1].effective_priority, item[0]))
        remaining = self.max_chars
        bounded: list[ContextFragment] = []
        for _, fragment in selected:
            if remaining <= 0:
                break
            content = fragment.content[:remaining]
            if content:
                bounded.append(
                    ContextFragment(
                        fragment.kind,
                        content,
                        fragment.source,
                        fragment.role,
                        fragment.priority,
                        fragment.metadata,
                    )
                )
                remaining -= len(content)
        return tuple(bounded)

    def messages(self) -> tuple[Message, ...]:
        return tuple(fragment.render() for fragment in self.ordered())


_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def redact_text(value: str) -> str:
    redacted = value
    redacted = _SECRET_PATTERNS[0].sub(r"\1\2[REDACTED]", redacted)
    redacted = _SECRET_PATTERNS[1].sub("[REDACTED]", redacted)
    return redacted


@dataclass(frozen=True, slots=True)
class ContextDebugEntry:
    kind: ContextKind
    source: str
    role: MessageRole
    priority: int
    content: str


@dataclass(frozen=True, slots=True)
class ContextDebugSnapshot:
    thread_id: str
    entries: tuple[ContextDebugEntry, ...]
    history_messages: int
    estimated_characters: int
