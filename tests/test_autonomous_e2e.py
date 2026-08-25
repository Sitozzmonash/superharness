from __future__ import annotations

import os

import pytest

from super_harness import Agent, AgentManager, AgentStatus, DeepSeekProvider, SpawnRequest


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_real_deepseek_autonomous_spawn_wait_aggregate() -> None:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is not configured")

    def factory(request: SpawnRequest) -> Agent:
        return Agent(
            DeepSeekProvider(),
            instructions=request.instructions,
            context=request.inherited_context,
        )

    manager = AgentManager(Agent(DeepSeekProvider()), factory)
    try:
        response = await manager.thread(manager.root_agent_id).arun(
            "Call spawn_agent once with task 'Return exactly CHILD_OK'. Then call wait_agent for "
            "that child. After it completes, answer exactly PARENT_OK."
        )
        children = manager.list_agents(parent_agent_id=manager.root_agent_id)
    finally:
        await manager.aclose()

    assert response.text.strip() == "PARENT_OK"
    assert len(children) == 1
    assert children[0].status is AgentStatus.COMPLETED
    assert children[0].result is not None and "CHILD_OK" in children[0].result.text
