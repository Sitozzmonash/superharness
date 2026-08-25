"""Resume a failed parent and its nested workflow from stable checkpoints."""

import asyncio
import tempfile
from pathlib import Path

from super_harness import (
    Edge,
    JSONWorkflowStore,
    Node,
    Workflow,
    WorkflowContext,
    WorkflowEngine,
    subworkflow_node,
)

service_ready = False


def publish(_: WorkflowContext) -> str:
    if not service_ready:
        raise ConnectionError("service is temporarily unavailable")
    return "published"


async def main() -> None:
    global service_ready
    child = Workflow(
        "release-child",
        [Node("build", lambda _: "artifact"), Node("publish", publish)],
        [Edge("build", "publish")],
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        child_engine = WorkflowEngine(store=JSONWorkflowStore(root / "child"))
        parent_store = JSONWorkflowStore(root / "parent")
        parent_engine = WorkflowEngine(store=parent_store)
        parent = Workflow(
            "release-parent",
            [subworkflow_node("release", child, engine=child_engine)],
        )

        failed = await parent_engine.run(parent, run_id="release-run")
        print("first:", failed.status)
        service_ready = True
        resumed = await parent_engine.resume(parent, parent_store.load("release-run"))
        print("resumed:", resumed.status, resumed.output)


if __name__ == "__main__":
    asyncio.run(main())
