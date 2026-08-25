"""Route input to exactly one specialist node."""

import asyncio

from super_harness import Edge, Node, NodeKind, NodeOutput, Workflow, WorkflowEngine


async def main() -> None:
    workflow = Workflow(
        "support-router",
        [
            Node(
                "route",
                lambda context: NodeOutput(
                    route="billing" if "invoice" in str(context.workflow_input) else "technical"
                ),
                NodeKind.ROUTER,
            ),
            Node("billing", lambda _: "billing specialist"),
            Node("technical", lambda _: "technical specialist"),
        ],
        [
            Edge("route", "billing", route="billing"),
            Edge("route", "technical", route="technical"),
        ],
    )
    run = await WorkflowEngine().run(workflow, "My invoice is incorrect")
    selected = next(
        event.payload["route"] for event in run.events if event.type == "route.selected"
    )
    print(selected)


if __name__ == "__main__":
    asyncio.run(main())
