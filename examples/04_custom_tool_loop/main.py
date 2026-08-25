"""Run a complete DeepSeek function-tool loop."""

import asyncio

from super_harness import Agent, DeepSeekProvider, tool


@tool
def weather(city: str) -> dict[str, object]:
    """Get example weather for a city."""

    return {"city": city, "temperature_c": 25, "condition": "sunny"}


async def main() -> None:
    provider = DeepSeekProvider()
    agent = Agent(provider, tools=[weather])
    try:
        response = await agent.arun(
            "Call the weather tool for Chengdu and then answer with the result."
        )
        print(response.text)
    finally:
        await agent.aclose()


if __name__ == "__main__":
    asyncio.run(main())
