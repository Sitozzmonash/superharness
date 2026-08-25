from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from super_harness import (
    Agent,
    MemoryCandidate,
    MemoryKind,
    MemoryManager,
    MemoryTrace,
    SQLiteMemoryStore,
    WorkingMemory,
)
from super_harness.context import ContextKind
from super_harness.memory import MemoryError
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class ContextModel:
    name = "memory-context-model"
    capabilities = ModelCapabilities(tools=False, structured_output=False)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        context = "\n".join(message.content for message in request.messages)
        answer = "jasmine tea" if "jasmine tea" in context else "unknown"
        return ModelResponse(answer)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        response = await self.complete(request)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=response)

    async def aclose(self) -> None:
        return


class CustomExtractor:
    async def extract(self, messages: Sequence[Message]) -> tuple[MemoryCandidate, ...]:
        return (MemoryCandidate("custom consolidated memory", MemoryKind.SUMMARY),)


def test_working_memory_is_bounded_lru_and_renders_data_context() -> None:
    memory = WorkingMemory(max_items=2)
    memory.set("task", "ship")
    memory.set("branch", "main")
    assert memory.get("task") == "ship"
    memory.set("owner", "Sito")

    assert memory.snapshot() == {"task": "ship", "owner": "Sito"}
    fragment = memory.context()
    assert fragment is not None
    assert fragment.kind is ContextKind.MEMORY
    assert fragment.role is MessageRole.USER
    assert memory.delete("task")
    assert not memory.delete("missing")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sqlite_memory_cross_thread_dedupe_reopen_and_forget(tmp_path: Path) -> None:
    path = tmp_path / "memory.sqlite3"
    store = SQLiteMemoryStore(path)
    first = await store.remember(
        MemoryCandidate(
            "The preferred drink is jasmine tea", MemoryKind.PREFERENCE, ("profile",), 0.9
        ),
        source_thread_id="thread-a",
    )
    duplicate = await store.remember(
        MemoryCandidate(
            "  The preferred drink is jasmine tea  ", MemoryKind.PREFERENCE, importance=0.6
        ),
        source_thread_id="thread-b",
    )
    other = await store.remember(
        MemoryCandidate("Release uses a canary", MemoryKind.DECISION),
        source_thread_id="thread-b",
    )
    await store.close()

    assert first.memory_id == duplicate.memory_id
    store = SQLiteMemoryStore(path)
    matches = await store.search("preferred jasmine drink", exclude_thread_id="thread-b")
    loaded = await store.get(first.memory_id)
    assert [item.record.memory_id for item in matches] == [first.memory_id]
    assert loaded is not None and loaded.tags == ("profile",)
    assert await store.forget(other.memory_id)
    assert await store.get(other.memory_id) is None
    await store.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_extraction_consolidation_retrieval_and_agent_chain(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    traces: list[MemoryTrace] = []
    manager = MemoryManager(store, trace_sink=traces.append)
    records = await manager.consolidate(
        "thread-a",
        [Message(MessageRole.USER, "Remember: The preferred drink is jasmine tea")],
    )
    ignored = await manager.consolidate(
        "thread-b", [Message(MessageRole.USER, "This is ordinary transient text")]
    )
    context = await manager.retrieve_context(
        "preferred jasmine drink", current_thread_id="thread-b"
    )
    answer = await Agent(ContextModel(), context=context).arun("What drink is preferred?")

    assert len(records) == 1
    assert ignored == ()
    assert context[0].source.startswith("memory:")
    assert context[0].metadata["source_thread_id"] == "thread-a"
    assert answer.text == "jasmine tea"
    assert [trace.operation for trace in traces] == ["consolidate", "consolidate", "retrieve"]

    custom = MemoryManager(store, CustomExtractor())
    custom_records = await custom.consolidate("thread-c", [])
    assert custom_records[0].kind is MemoryKind.SUMMARY
    await store.close()


def test_sqlite_memory_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO memory_meta VALUES ('schema_version', '999')")
    connection.commit()
    connection.close()

    with pytest.raises(MemoryError, match="newer"):
        SQLiteMemoryStore(path)
