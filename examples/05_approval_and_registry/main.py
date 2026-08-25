"""Use registry and callback approval without a model call."""

import asyncio

from super_harness import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    ToolExecutor,
    ToolRegistry,
    tool,
)
from super_harness.models import ToolCall


@tool(risk="write")
def publish(message: str) -> str:
    """Publish an example message."""

    return f"published: {message}"


def review(request: ApprovalRequest) -> ApprovalDecision:
    print(f"reviewing {request.tool.qualified_name}: {dict(request.arguments)}")
    return ApprovalDecision.DENY


async def main() -> None:
    registry = ToolRegistry([publish])
    executor = ToolExecutor(registry, approval=ApprovalPolicy(callback=review))
    call = ToolCall("call_1", "publish", {"message": "hello"}, '{"message":"hello"}')
    print(await executor.execute(call))


if __name__ == "__main__":
    asyncio.run(main())
