"""Select one branch with a boolean gate and rejoin safely."""

import asyncio

from super_harness import Edge, Node, NodeKind, Workflow, WorkflowEngine


async def main() -> None:
    workflow = Workflow(
        "approval-gate",
        [
            Node("approved", lambda context: context.workflow_input, NodeKind.GATE),
            Node("deploy", lambda _: "deployed"),
            Node("hold", lambda _: "held for review"),
            Node(
                "notify",
                lambda context: next(
                    result.value
                    for result in context.results.values()
                    if result.node_id in {"deploy", "hold"} and result.value is not None
                ),
            ),
        ],
        [
            Edge("approved", "deploy", route="true"),
            Edge("approved", "hold", route="false"),
            Edge("deploy", "notify"),
            Edge("hold", "notify"),
        ],
    )
    run = await WorkflowEngine().run(workflow, True)
    print(run.output)


if __name__ == "__main__":
    asyncio.run(main())
