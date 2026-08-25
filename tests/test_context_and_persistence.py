from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from super_harness import (
    Agent,
    AgentsMdLoader,
    ContextAssembler,
    ContextFragment,
    ContextKind,
    SQLiteThreadStore,
)
from super_harness.models import (
    Message,
    MessageRole,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
)


class EchoProvider:
    name = "echo"
    capabilities = ModelCapabilities()

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse("ok")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("ok"))

    async def aclose(self) -> None:
        return None


def test_context_precedence_dedup_budget_and_redaction() -> None:
    assembler = ContextAssembler(max_chars=12)
    assembler.extend(
        [
            ContextFragment(ContextKind.RAG, "retrieved", "rag:1"),
            ContextFragment(ContextKind.DEVELOPER, "rules", "app"),
            ContextFragment(ContextKind.DEVELOPER, "rules", "app"),
            ContextFragment(ContextKind.PROJECT, "project", "AGENTS.md"),
        ]
    )

    ordered = assembler.ordered()
    assert [(item.kind, item.content) for item in ordered] == [
        (ContextKind.DEVELOPER, "rules"),
        (ContextKind.PROJECT, "project"),
    ]

    thread = Agent(
        EchoProvider(),
        context=[ContextFragment(ContextKind.MEMORY, "api_key=very-secret", "memory")],
    ).thread()
    snapshot = thread.debug_context()
    assert snapshot.entries[0].content == "api_key=[REDACTED]"
    assert "very-secret" not in repr(snapshot)


def test_agents_md_root_nested_override_order_and_budget(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("root", encoding="utf-8")
    (tmp_path / "a" / "AGENTS.md").write_text("ignored", encoding="utf-8")
    (tmp_path / "a" / "AGENTS.override.md").write_text("override", encoding="utf-8")
    (nested / "AGENTS.md").write_text("nested", encoding="utf-8")

    loader = AgentsMdLoader(max_bytes=12)
    paths = loader.discover(nested)
    fragments = loader.load(nested)

    assert [path.name for path in paths] == [
        "AGENTS.md",
        "AGENTS.override.md",
        "AGENTS.md",
    ]
    assert [fragment.content for fragment in fragments] == ["root", "override"]
    assert all(str(tmp_path) in fragment.source for fragment in fragments)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sqlite_restart_resume_fork_archive_and_neutral_values(tmp_path: Path) -> None:
    database = tmp_path / "threads.db"
    provider = EchoProvider()
    with SQLiteThreadStore(database) as store:
        agent = Agent(provider, instructions="persist me", store=store)
        thread = agent.thread()
        await thread.arun("first")
        call = ToolCall("call_1", "demo", {"value": 1}, '{"value":1}')
        thread.messages.append(Message(MessageRole.ASSISTANT, "", tool_calls=(call,)))
        thread.metadata["label"] = "durable"
        thread.compact("accepted decision", retain_messages=2)
        store.save(thread)
        thread_id = thread.thread_id

    with SQLiteThreadStore(database) as reopened:
        agent = Agent(EchoProvider(), store=reopened)
        resumed = agent.resume(thread_id)
        forked = agent.fork(thread_id)

        assert resumed.thread_id == thread_id
        assert resumed.instructions == "persist me"
        assert resumed.metadata == {"label": "durable"}
        assert resumed.messages[-1].tool_calls[0].arguments == {"value": 1}
        assert resumed.summaries[-1].content == "accepted decision"
        assert forked.thread_id != resumed.thread_id
        assert forked.parent_thread_id == resumed.thread_id
        forked.messages.append(Message(MessageRole.USER, "fork only"))
        assert resumed.messages[-1].content != "fork only"

        resumed.archive()
        assert resumed.thread_id not in reopened.ids()
        assert resumed.thread_id in reopened.ids(include_archived=True)
        with pytest.raises(RuntimeError, match="archived"):
            await resumed.arun("blocked")


@pytest.mark.asyncio
async def test_manual_and_automatic_compaction_preserve_security_state() -> None:
    provider = EchoProvider()
    thread = Agent(provider, compaction_threshold_chars=40).thread()
    thread.compaction_retain_messages = 2
    thread.messages.extend(
        [
            Message(MessageRole.USER, "goal: finish the work"),
            Message(MessageRole.ASSISTANT, "approval denied; sandbox stays read_only"),
            Message(MessageRole.USER, "decision one"),
            Message(MessageRole.ASSISTANT, "decision two"),
        ]
    )

    events = [event async for event in thread.astream("continue now")]

    assert "compaction.started" in [event.type for event in events]
    assert "compaction.completed" in [event.type for event in events]
    assert len(thread.summaries) == 1
    assert "Security and permission state" in thread.summaries[0].content
    assert "sandbox stays read_only" in thread.summaries[0].content
    request_text = "\n".join(message.content for message in provider.requests[0].messages)
    assert "summary:" in request_text
    assert "continue now" in request_text

    thread.messages.extend(
        [Message(MessageRole.USER, "later one"), Message(MessageRole.ASSISTANT, "later two")]
    )
    previous_count = thread.summaries[0].summarized_messages
    thread.compact(retain_messages=2)
    assert len(thread.summaries) == 1
    assert thread.summaries[0].summarized_messages > previous_count


def test_sqlite_rejects_newer_schema_version(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version=999")
    connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        SQLiteThreadStore(database)
