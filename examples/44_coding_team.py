import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=request.instructions)


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        members = await asyncio.gather(
            manager.spawn_agent(manager.root_agent_id, "Propose the implementation", role="coder"),
            manager.spawn_agent(manager.root_agent_id, "Find correctness risks", role="reviewer"),
            manager.spawn_agent(manager.root_agent_id, "Design the tests", role="tester"),
        )
        await manager.wait_all([member.agent_id for member in members], timeout=300)
        for result in manager.results():
            print(result.status, result.text)
    finally:
        await manager.aclose()


asyncio.run(main())
