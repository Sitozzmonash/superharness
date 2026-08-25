"""Tool approval policy boundary."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from super_harness.exceptions import ApprovalDenied

from .definition import Tool


class ApprovalDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    tool: Tool
    arguments: Mapping[str, Any]
    call_id: str


ApprovalCallback = Callable[[ApprovalRequest], ApprovalDecision | Awaitable[ApprovalDecision]]


class ApprovalPolicy:
    def __init__(
        self,
        *,
        default: ApprovalDecision = ApprovalDecision.ALLOW,
        callback: ApprovalCallback | None = None,
    ) -> None:
        self.default = default
        self.callback = callback

    @classmethod
    def full_access(cls) -> ApprovalPolicy:
        return cls(default=ApprovalDecision.ALLOW)

    @classmethod
    def deny_all(cls) -> ApprovalPolicy:
        return cls(default=ApprovalDecision.DENY)

    async def require(self, request: ApprovalRequest) -> None:
        decision: ApprovalDecision | Awaitable[ApprovalDecision]
        decision = self.default if self.callback is None else self.callback(request)
        if inspect.isawaitable(decision):
            decision = await decision
        if decision is not ApprovalDecision.ALLOW:
            raise ApprovalDenied(
                f"approval denied for tool {request.tool.qualified_name}",
                correlation_id=request.call_id,
                details={"tool": request.tool.qualified_name},
            )
