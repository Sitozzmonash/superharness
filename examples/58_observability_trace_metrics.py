"""Inspect a workflow trace tree and in-memory metrics snapshot."""

import asyncio

from super_harness import Node, Observability, StructuredLogger, Workflow, WorkflowEngine


async def main() -> None:
    observer = Observability(logger=StructuredLogger(console=None))
    workflow = Workflow(
        "trace-demo",
        [Node("prepare", lambda _: "ready"), Node("finish", lambda _: "done")],
    )
    run = await WorkflowEngine(event_listener=observer.observe).run(workflow)
    trace_id = next(span.trace_id for span in observer.tracer.spans() if span.name == "workflow")
    print(observer.tracer.tree(trace_id))
    print(observer.metrics.snapshot().counters)
    print(run.output)


if __name__ == "__main__":
    asyncio.run(main())
