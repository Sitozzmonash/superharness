import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, MultiAgentLimits, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider())


async def main() -> None:
    limits = MultiAgentLimits(max_active_agents=2, max_depth=2, total_token_budget=2_000)
    manager = AgentManager(Agent(DeepSeekProvider()), factory, limits=limits)
    try:
        child = await manager.spawn_agent(
            manager.root_agent_id, "Explore many alternatives", timeout=60, token_budget=1_000
        )
        await asyncio.sleep(0.1)
        await manager.interrupt_agent(child.agent_id)
        print(manager.get(child.agent_id).status, manager.tokens_used)
    finally:
        await manager.aclose()


asyncio.run(main())
