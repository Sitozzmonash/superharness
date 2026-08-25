import asyncio

from super_harness import Agent, AgentManager, DeepSeekProvider, SpawnRequest


def factory(request: SpawnRequest) -> Agent:
    return Agent(DeepSeekProvider(), instructions=f"You are the {request.role} critic.")


async def main() -> None:
    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        critics = [
            await manager.spawn_agent(manager.root_agent_id, "Critique the proposal", role=role)
            for role in ("security", "reliability", "usability")
        ]
        await manager.wait_all([critic.agent_id for critic in critics], timeout=300)
        print("\n\n".join(result.text for result in manager.results()))
    finally:
        await manager.aclose()


asyncio.run(main())
