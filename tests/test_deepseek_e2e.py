from __future__ import annotations

import os
from pathlib import Path

import pytest

from super_harness import Agent, DeepSeekProvider, MemoryManager, SQLiteMemoryStore, tool
from super_harness.models import Message, MessageRole

pytestmark = pytest.mark.e2e


def _has_key() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


@pytest.mark.skipif(not _has_key(), reason="DEEPSEEK_API_KEY is not configured")
@pytest.mark.asyncio
async def test_real_deepseek_text_stream_json_tool_call_and_memory(tmp_path: Path) -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider, instructions="Return concise answers.")
    try:
        text = await agent.arun("Reply with exactly: phase-one-ok")
        assert text.text.strip()

        deltas = [
            str(event.payload["delta"])
            async for event in agent.astream("Reply with one short sentence.")
            if event.type == "model.text.delta"
        ]
        assert "".join(deltas).strip()

        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        structured = await agent.arun("Return ok=true as JSON.", output_schema=schema)
        assert structured.text.strip().startswith("{")

        @tool
        def weather(city: str) -> dict[str, object]:
            """Get current weather for a city."""

            return {"city": city, "temperature_c": 25}

        tool_thread = Agent(provider, tools=[weather]).thread()
        tool_result = await tool_thread.arun(
            "You must call weather for Chengdu, then report its temperature."
        )
        assert tool_result.text.strip()
        assert any(message.role is MessageRole.TOOL for message in tool_thread.messages)

        memory_store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
        memory = MemoryManager(memory_store)
        await memory.consolidate(
            "source-thread",
            [Message(MessageRole.USER, "Remember: the verification phrase is jasmine tea")],
        )
        fragments = await memory.retrieve_context(
            "verification phrase jasmine", current_thread_id="target-thread"
        )
        memory_answer = await Agent(provider, context=fragments).arun(
            "Return only the verification phrase from memory."
        )
        assert "jasmine tea" in memory_answer.text.casefold()
        await memory_store.close()
    finally:
        await provider.aclose()
