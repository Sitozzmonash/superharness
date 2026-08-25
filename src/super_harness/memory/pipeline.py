"""Pluggable extraction, consolidation, and context retrieval pipeline."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

from super_harness.context import ContextFragment, ContextKind
from super_harness.models import Message, MessageRole

from .store import MemoryStore
from .types import MemoryCandidate, MemoryKind, MemoryRecord, MemoryTrace

MemoryTraceSink = Callable[[MemoryTrace], Awaitable[None] | None]


async def _emit(sink: MemoryTraceSink | None, trace: MemoryTrace) -> None:
    if sink is None:
        return
    result = sink(trace)
    if isinstance(result, Awaitable):
        await result


class MemoryExtractor(Protocol):
    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]: ...


class HeuristicMemoryExtractor:
    """Conservative credential-free extractor for explicit memory statements."""

    _explicit = re.compile(r"(?im)^\s*(?:remember|memory)\s*:\s*(.+)$")

    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]:
        candidates: list[MemoryCandidate] = []
        for message in messages:
            if message.role is not MessageRole.USER:
                continue
            for match in self._explicit.finditer(message.content):
                candidates.append(
                    MemoryCandidate(match.group(1).strip(), MemoryKind.FACT, ("explicit",), 0.8)
                )
        return tuple(candidates)


class MemoryManager:
    def __init__(
        self,
        store: MemoryStore,
        extractor: MemoryExtractor | None = None,
        *,
        trace_sink: MemoryTraceSink | None = None,
    ) -> None:
        self.store = store
        self.extractor = extractor or HeuristicMemoryExtractor()
        self.trace_sink = trace_sink

    async def consolidate(
        self, thread_id: str, messages: Sequence[Message]
    ) -> tuple[MemoryRecord, ...]:
        candidates = await self.extractor.extract(messages)
        records = tuple(
            [
                await self.store.remember(candidate, source_thread_id=thread_id)
                for candidate in candidates
            ]
        )
        await _emit(self.trace_sink, MemoryTrace("consolidate", True, len(records), thread_id))
        return records

    async def retrieve_context(
        self,
        query: str,
        *,
        current_thread_id: str | None = None,
        limit: int = 5,
    ) -> tuple[ContextFragment, ...]:
        matches = await self.store.search(query, limit=limit, exclude_thread_id=current_thread_id)
        fragments = tuple(
            ContextFragment(
                ContextKind.MEMORY,
                match.record.content,
                f"memory:{match.record.memory_id}",
                metadata={
                    "score": match.score,
                    "kind": match.record.kind.value,
                    "source_thread_id": match.record.source_thread_id,
                },
            )
            for match in matches
        )
        await _emit(
            self.trace_sink,
            MemoryTrace("retrieve", True, len(fragments), current_thread_id),
        )
        return fragments
