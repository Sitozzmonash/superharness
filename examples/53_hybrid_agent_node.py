"""Run an autonomous Agent as one deterministic workflow node."""

import asyncio
from collections.abc import AsyncIterator

from super_harness import Agent, AgentManager, SpawnRequest, Workflow, WorkflowEngine, agent_node
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class DemoProvider:
    name = "demo"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(f"agent handled: {request.messages[-1].content}"),
        )

    async def aclose(self) -> None:
        return None


def factory(_: SpawnRequest) -> Agent:
    return Agent(DemoProvider())


async def main() -> None:
    manager = AgentManager(Agent(DemoProvider()), factory)
    workflow = Workflow(
        "agent-node",
        [agent_node("researcher", manager, lambda context: f"research {context.workflow_input}")],
    )
    run = await WorkflowEngine().run(workflow, "Python workflows")
    print(run.output)
    print([event.type for event in run.events if event.payload.get("source")])


if __name__ == "__main__":
    asyncio.run(main())
