"""Normalized bounded tool results."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    output: str
    success: bool
    truncated: bool = False
    original_chars: int = 0
    error_type: str | None = None


def stringify_output(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    try:
        return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def truncate_output(value: str, limit: int) -> tuple[str, bool, int]:
    size = len(value)
    if size <= limit:
        return value, False, size
    marker = f"\n... truncated {size - limit} characters ...\n"
    available = max(limit - len(marker), 2)
    head = available // 2
    tail = available - head
    return f"{value[:head]}{marker}{value[-tail:]}", True, size
