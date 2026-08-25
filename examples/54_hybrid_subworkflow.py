"""Nest a reusable workflow inside a parent workflow."""

import asyncio
import tempfile
from pathlib import Path

from super_harness import (
    Edge,
    JSONWorkflowStore,
    Node,
    Workflow,
    WorkflowEngine,
    subworkflow_node,
)


async def main() -> None:
    child = Workflow(
        "normalize",
        [
            Node("strip", lambda context: str(context.workflow_input).strip()),
            Node("upper", lambda context: str(context.results["strip"].value).upper()),
        ],
        [Edge("strip", "upper")],
    )
    with tempfile.TemporaryDirectory() as directory:
        child_engine = WorkflowEngine(store=JSONWorkflowStore(Path(directory) / "child"))
        parent = Workflow(
            "publish",
            [
                subworkflow_node("normalize", child, engine=child_engine),
                Node("publish", lambda context: f"published:{context.results['normalize'].value}"),
            ],
            [Edge("normalize", "publish")],
        )
        run = await WorkflowEngine().run(parent, "  release note  ", run_id="demo")
        print(run.output)
        print(run.state.values["hybrid.normalize.run_id"])


if __name__ == "__main__":
    asyncio.run(main())
