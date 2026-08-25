"""Run a deterministic three-step workflow."""

import asyncio

from super_harness import Edge, Node, NodeOutput, Workflow, WorkflowEngine


async def main() -> None:
    workflow = Workflow(
        "publish-article",
        [
            Node("draft", lambda context: str(context.workflow_input).strip()),
            Node(
                "review",
                lambda context: NodeOutput(
                    context.results["draft"].value,
                    {"reviewed": True},
                ),
            ),
            Node(
                "publish",
                lambda context: {
                    "text": context.results["review"].value,
                    "reviewed": context.state["reviewed"],
                },
            ),
        ],
        [Edge("draft", "review"), Edge("review", "publish")],
    )
    run = await WorkflowEngine().run(workflow, "  Hello workflows  ")
    print(run.status, run.output)


if __name__ == "__main__":
    asyncio.run(main())
