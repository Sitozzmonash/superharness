"""Deny every Tool call before its handler can run."""

import asyncio

from super_harness import ApprovalPolicy, ToolExecutor, ToolRegistry, tool
from super_harness.models import ToolCall


@tool(risk="write")
def destructive() -> str:
    """Represent a side effect that must not execute."""
    raise RuntimeError("must not run")


result = asyncio.run(
    ToolExecutor(ToolRegistry((destructive,)), approval=ApprovalPolicy.deny_all()).execute(
        ToolCall("1", "destructive", {}, "{}")
    )
)
print(result.success, result.error_type)

