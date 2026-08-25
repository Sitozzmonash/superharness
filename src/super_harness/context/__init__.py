"""Context assembly and project instruction discovery."""

from .agents_md import AgentsMdLoader
from .compaction import ContextSummary, extractive_summary
from .fragments import (
    ContextAssembler,
    ContextDebugEntry,
    ContextDebugSnapshot,
    ContextFragment,
    ContextKind,
    ContextPriority,
    redact_text,
)

__all__ = [
    "AgentsMdLoader",
    "ContextAssembler",
    "ContextDebugEntry",
    "ContextDebugSnapshot",
    "ContextFragment",
    "ContextKind",
    "ContextPriority",
    "ContextSummary",
    "extractive_summary",
    "redact_text",
]
