"""Request strict JSON and normalize a provider tool call."""

import asyncio

from super_harness import Agent, DeepSeekProvider
from super_harness.models import ToolDefinition


async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider)
    schema = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
        "additionalProperties": False,
    }
    weather = ToolDefinition(
        "weather",
        "Get current weather for a city",
        {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
            "additionalProperties": False,
        },
    )
    try:
        structured = await agent.arun("Summarize Chengdu in JSON.", output_schema=schema)
        print(structured.text)
        tool_response = await agent.arun("Use weather for Chengdu.", tools=[weather])
        for call in tool_response.tool_calls:
            print(call.call_id, call.name, dict(call.arguments))
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
