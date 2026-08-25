"""Typed hook lifecycle values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any


def _mapping() -> Mapping[str, Any]:
    return {}


class HookEvent(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    USER_PROMPT = "user_prompt"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_COMPACT = "pre_compact"
    POST_COMPACT = "post_compact"
    SUBAGENT_START = "subagent_start"
    SUBAGENT_END = "subagent_end"
    ERROR = "error"


class HookFailurePolicy(StrEnum):
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class HookContext:
    event: HookEvent
    data: Mapping[str, Any] = field(default_factory=_mapping)
    thread_id: str | None = None
    turn_id: str | None = None
    source: str = "runtime"

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))


@dataclass(frozen=True, slots=True)
class HookResult:
    updates: Mapping[str, Any] = field(default_factory=_mapping)
    deny_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "updates", MappingProxyType(dict(self.updates)))
        if self.deny_reason is not None and not self.deny_reason.strip():
            raise ValueError("hook denial reason must be non-empty")

    @classmethod
    def enrich(cls, **updates: Any) -> HookResult:
        return cls(updates)

    @classmethod
    def deny(cls, reason: str) -> HookResult:
        return cls(deny_reason=reason)


@dataclass(frozen=True, slots=True)
class HookTrace:
    event: HookEvent
    hook: str
    source: str
    success: bool
    duration_ms: float
    denied: bool = False
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class HookOutcome:
    data: Mapping[str, Any]
    traces: tuple[HookTrace, ...] = ()
    denied: bool = False
    deny_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
