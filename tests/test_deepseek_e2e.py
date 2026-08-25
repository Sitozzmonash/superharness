from __future__ import annotations

import os

import pytest

from super_harness import Agent, DeepSeekProvider, tool
from super_harness.models import MessageRole

pytestmark = pytest.mark.e2e


def _has_key() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


@pytest.mark.skipif(not _has_key(), reason="DEEPSEEK_API_KEY is not configured")
@pytest.mark.asyncio
async def test_real_deepseek_text_stream_json_and_tool_call() -> None:
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
    finally:
        await provider.aclose()
