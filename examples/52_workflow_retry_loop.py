"""Combine an idempotent retry policy with a bounded explicit loop."""

import asyncio

from super_harness import Node, RetryPolicy, Workflow, WorkflowContext, WorkflowEngine

attempts = 0


def flaky_counter(context: WorkflowContext) -> int:
    global attempts
    attempts += 1
    if attempts == 1:
        raise ConnectionError("temporary service failure")
    return context.iteration


async def main() -> None:
    workflow = Workflow(
        "retry-loop",
        [
            Node(
                "poll",
                flaky_counter,
                retry=RetryPolicy(max_attempts=2, backoff_seconds=0.05),
                idempotent=True,
                loop_until=lambda _, value: value >= 3,
                max_iterations=4,
            )
        ],
    )
    run = await WorkflowEngine().run(workflow)
    print(run.status, run.output, run.node_results["poll"].attempts)


if __name__ == "__main__":
    asyncio.run(main())
