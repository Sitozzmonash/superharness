"""Allow a reviewed Tool call explicitly."""

import asyncio

from super_harness import ApprovalDecision, ApprovalPolicy, ToolExecutor, ToolRegistry, tool
from super_harness.models import ToolCall


@tool(risk="write")
def save(value: str) -> str:
    """Return a deterministic save result."""
    return f"saved:{value}"


policy = ApprovalPolicy(callback=lambda request: ApprovalDecision.ALLOW)
call = ToolCall("1", "save", {"value": "draft"}, '{"value":"draft"}')
print(asyncio.run(ToolExecutor(ToolRegistry((save,)), approval=policy).execute(call)))

