import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(
        DeepSeekProvider(), instructions=request.instructions, context=request.inherited_context
    )


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        response = await manager.thread(manager.root_agent_id).arun(
            "Split this research question between two subagents, wait for both, and synthesize: "
            "What makes an agent harness reliable?"
        )
        print(response.text)
    finally:
        await manager.aclose()


asyncio.run(main())
