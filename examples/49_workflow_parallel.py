"""Fan out work concurrently and join the branch results."""

import asyncio

from super_harness import Edge, Node, Workflow, WorkflowContext, WorkflowEngine


async def inspect(context: WorkflowContext) -> str:
    await asyncio.sleep(0.05)
    return f"{context.node_id}:{context.workflow_input}"


async def main() -> None:
    workflow = Workflow(
        "parallel-review",
        [
            Node("start", lambda _: "ready"),
            Node("security", inspect),
            Node("quality", inspect),
            Node("docs", inspect),
            Node(
                "join",
                lambda context: [
                    context.results[node_id].value
                    for node_id in ("security", "quality", "docs")
                ],
            ),
        ],
        [
            Edge("start", "security"),
            Edge("start", "quality"),
            Edge("start", "docs"),
            Edge("security", "join"),
            Edge("quality", "join"),
            Edge("docs", "join"),
        ],
    )
    run = await WorkflowEngine(max_concurrency=3).run(workflow, "release-1")
    print(run.output)


if __name__ == "__main__":
    asyncio.run(main())
