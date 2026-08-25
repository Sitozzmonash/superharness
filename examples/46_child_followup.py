import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=request.instructions)


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        child = await manager.spawn_agent(manager.root_agent_id, "Draft a release checklist")
        await manager.wait_all([child.agent_id], timeout=300)
        await manager.send_input(child.agent_id, "Now make it five bullets maximum")
        await manager.resume_agent(child.agent_id)
        final = (await manager.wait_all([child.agent_id], timeout=300))[0]
        print(final.result.text if final.result else final.status)
    finally:
        await manager.aclose()


asyncio.run(main())
