"""Public package surface for Super Harness."""

from super_harness.agent import Agent
from super_harness.config import HarnessConfig, ProfileName, SecretValue
from super_harness.exceptions import SuperHarnessError
from super_harness.models import DeepSeekProvider, OpenAICompatibleProvider
from super_harness.runtime.events import Event
from super_harness.runtime.thread import Thread
from super_harness.runtime.turn import Turn, TurnStatus
from super_harness.tools import (
    ApprovalDecision,
    ApprovalPolicy,
    ApprovalRequest,
    LocalSandbox,
    SandboxMode,
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    basic_builtin_tools,
    tool,
)

__all__ = [
    "Agent",
    "ApprovalDecision",
    "ApprovalPolicy",
    "ApprovalRequest",
    "DeepSeekProvider",
    "Event",
    "HarnessConfig",
    "LocalSandbox",
    "OpenAICompatibleProvider",
    "ProfileName",
    "SandboxMode",
    "SecretValue",
    "SuperHarnessError",
    "Thread",
    "Tool",
    "ToolExecutor",
    "ToolRegistry",
    "ToolResult",
    "Turn",
    "TurnStatus",
    "basic_builtin_tools",
    "tool",
]

__version__ = "0.0.1.dev0"
