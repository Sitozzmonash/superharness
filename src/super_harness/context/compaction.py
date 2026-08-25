"""Deterministic context compaction values and extractive summarizer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

from super_harness.models import Message


@dataclass(frozen=True, slots=True)
class ContextSummary:
    content: str
    summarized_messages: int
    summary_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def extractive_summary(messages: list[Message], *, max_chars: int = 8_000) -> str:
    """Build a bounded continuation summary without another model request."""

    lines: list[str] = []
    security: list[str] = []
    keywords = ("permission", "approval", "sandbox", "secret", "credential", "denied")
    for message in messages:
        content = " ".join(message.content.split())
        if not content:
            continue
        line = f"- {message.role.value}: {content[:600]}"
        lines.append(line)
        if any(keyword in content.casefold() for keyword in keywords):
            security.append(line)
    parts = ["Conversation facts:", *lines]
    if security:
        parts.extend(["Security and permission state (preserve):", *security])
    result = "\n".join(parts)
    if len(result) <= max_chars:
        return result
    head = max_chars * 2 // 3
    tail = max_chars - head
    return f"{result[:head]}\n... summary truncated ...\n{result[-tail:]}"
