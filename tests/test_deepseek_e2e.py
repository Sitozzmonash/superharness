from __future__ import annotations

import os

import pytest

from super_harness import Agent, DeepSeekProvider
from super_harness.models import ToolDefinition

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

        tool = ToolDefinition(
            "weather",
            "Get current weather",
            {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        )
        call = await agent.arun("Use weather for Chengdu.", tools=[tool])
        assert call.tool_calls
        assert call.tool_calls[0].name == "weather"
    finally:
        await provider.aclose()
