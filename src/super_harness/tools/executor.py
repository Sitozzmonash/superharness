"""Validation, approval, timeout, execution, and output bounding."""

from __future__ import annotations

import asyncio

from super_harness.exceptions import ApprovalDenied, ToolError, ToolValidationError
from super_harness.models import ToolCall

from .approval import ApprovalPolicy, ApprovalRequest
from .registry import ToolRegistry
from .result import ToolResult, stringify_output, truncate_output


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        approval: ApprovalPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.approval = approval or ApprovalPolicy.full_access()

    async def execute(self, call: ToolCall) -> ToolResult:
        try:
            item = self.registry.get(call.name)
            arguments = item.validate(call.arguments)
            await self.approval.require(ApprovalRequest(item, arguments, call.call_id))
            value = await asyncio.wait_for(item.invoke(arguments), timeout=item.metadata.timeout)
            output = stringify_output(value)
            bounded, truncated, original_chars = truncate_output(
                output, item.metadata.max_output_chars
            )
            return ToolResult(
                call.call_id,
                item.qualified_name,
                bounded,
                True,
                truncated,
                original_chars,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return ToolResult(
                call.call_id,
                call.name,
                f"tool {call.name} timed out",
                False,
                error_type="TimeoutError",
            )
        except (ApprovalDenied, ToolValidationError, ToolError) as exc:
            return ToolResult(
                call.call_id,
                call.name,
                str(exc),
                False,
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            return ToolResult(
                call.call_id,
                call.name,
                f"tool {call.name} failed: {exc}",
                False,
                error_type=type(exc).__name__,
            )
