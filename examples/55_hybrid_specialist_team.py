"""Let a workflow Agent autonomously spawn and join a specialist team."""

import asyncio
import json
from collections.abc import AsyncIterator

from super_harness import Agent, AgentManager, SpawnRequest, Workflow, WorkflowEngine, agent_node
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
    ToolCall,
)


class SpecialistProvider:
    name = "specialist"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(f"finding:{request.messages[-1].content}"),
        )

    async def aclose(self) -> None:
        return None


class LeadProvider:
    name = "lead"
    capabilities = ModelCapabilities()

    def __init__(self) -> None:
        self.step = 0
        self.children: list[str] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("unused")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.step += 1
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        if self.step <= 2:
            if self.step == 2:
                self.children.append(str(json.loads(request.messages[-1].content)["agent_id"]))
            arguments = {"task": f"analyze-part-{self.step}", "role": "specialist"}
            call = ToolCall(
                f"spawn-{self.step}",
                "spawn_agent",
                arguments,
                json.dumps(arguments),
            )
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(tool_calls=(call,)),
            )
            return
        if self.step == 3:
            self.children.append(str(json.loads(request.messages[-1].content)["agent_id"]))
            arguments = {"agent_ids": self.children, "timeout": 2.0}
            call = ToolCall("wait", "wait_agent", arguments, json.dumps(arguments))
            yield ModelStreamEvent(
                ModelStreamEventType.COMPLETED,
                response=ModelResponse(tool_calls=(call,)),
            )
            return
        results = json.loads(request.messages[-1].content)
        yield ModelStreamEvent(
            ModelStreamEventType.COMPLETED,
            response=ModelResponse(f"aggregated {len(results)} specialist results"),
        )

    async def aclose(self) -> None:
        return None


lead = LeadProvider()


def factory(request: SpawnRequest) -> Agent:
    return Agent(lead if request.role == "lead" else SpecialistProvider())


async def main() -> None:
    manager = AgentManager(Agent(SpecialistProvider()), factory)
    workflow = Workflow(
        "team-pipeline",
        [agent_node("team", manager, "coordinate the analysis", role="lead", timeout=2)],
    )
    run = await WorkflowEngine().run(workflow)
    print(run.output)
    print("agents:", len(manager.list_agents()) - 1)


if __name__ == "__main__":
    asyncio.run(main())
