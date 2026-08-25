from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest

from super_harness import (
    ApprovalDecision,
    ApprovalPolicy,
    LocalSandbox,
    SandboxMode,
    Tool,
    ToolExecutor,
    ToolRegistry,
    tool,
)
from super_harness.exceptions import SandboxError, ToolError, ToolValidationError
from super_harness.models import ToolCall
from super_harness.tools import (
    file_read_tool,
    file_search_tool,
    file_write_tool,
    python_tool,
    shell_tool,
)


def _call(name: str, arguments: dict[str, object], call_id: str = "call_1") -> ToolCall:
    import json

    return ToolCall(call_id, name, arguments, json.dumps(arguments))


def test_tool_decorator_builds_schema_and_validates() -> None:
    @tool(description="Add two integers", namespace="math")
    def add(left: int, right: int = 1) -> int:
        return left + right

    assert isinstance(add, Tool)
    assert add.qualified_name == "math.add"
    schema = add.provider_definition().parameters
    assert schema["properties"]["left"]["type"] == "integer"
    assert schema["required"] == ["left"]
    assert add.validate({"left": 2}) == {"left": 2, "right": 1}
    with pytest.raises(ToolValidationError):
        add.validate({"left": "not-an-integer", "extra": True})


def test_tool_requires_annotations_and_rejects_variadic_parameters() -> None:
    def missing(value: object, other: object) -> None:
        return None

    missing.__annotations__.pop("other")

    def variadic(*values: int) -> None:
        return None

    with pytest.raises(TypeError, match="annotation"):
        tool(missing)
    with pytest.raises(TypeError, match="args"):
        tool(variadic)


def test_registry_conflicts_state_order_search_and_deferred_visibility() -> None:
    @tool
    def first(value: str) -> str:
        """Echo a value."""

        return value

    @tool(namespace="extra", deferred=True)
    def second(value: str) -> str:
        """Find a second value."""

        return value

    registry = ToolRegistry([first, second])

    assert [item.qualified_name for item in registry.list()] == ["first", "extra.second"]
    assert [item.name for item in registry.search("second")] == ["second"]
    assert [item.name for item in registry.definitions()] == ["first"]
    assert len(registry.definitions(include_deferred=True)) == 2
    registry.disable("first")
    with pytest.raises(ToolError, match="disabled"):
        registry.get("first")
    registry.enable("first")
    with pytest.raises(ToolError, match="already registered"):
        registry.register(first)
    assert registry.unregister("first") is first


@pytest.mark.asyncio
async def test_executor_validation_approval_timeout_and_truncation() -> None:
    side_effects: list[int] = []

    @tool(max_output_chars=100)
    def mutate(value: int) -> str:
        side_effects.append(value)
        return "a" * 200

    denied = ToolExecutor(ToolRegistry([mutate]), approval=ApprovalPolicy.deny_all())
    denied_result = await denied.execute(_call("mutate", {"value": 1}))
    assert not denied_result.success
    assert denied_result.error_type == "ApprovalDenied"
    assert side_effects == []

    async def decide(request: object) -> ApprovalDecision:
        return ApprovalDecision.ALLOW

    allowed = ToolExecutor(ToolRegistry([mutate]), approval=ApprovalPolicy(callback=decide))
    result = await allowed.execute(_call("mutate", {"value": 2}))
    assert result.success and result.truncated
    assert result.original_chars == 200
    assert "truncated" in result.output
    assert side_effects == [2]

    invalid = await allowed.execute(_call("mutate", {"value": "bad"}))
    assert not invalid.success
    assert invalid.error_type == "ToolValidationError"

    @tool(timeout=0.01)
    async def slow() -> str:
        await asyncio.sleep(1)
        return "late"

    timed = await ToolExecutor(ToolRegistry([slow])).execute(_call("slow", {}))
    assert not timed.success
    assert timed.error_type == "TimeoutError"


def test_sandbox_path_policy(tmp_path: Path) -> None:
    readonly = LocalSandbox(tmp_path, SandboxMode.READ_ONLY)
    assert readonly.resolve("inside.txt") == tmp_path / "inside.txt"
    with pytest.raises(SandboxError, match="read-only"):
        readonly.resolve("inside.txt", write=True)
    with pytest.raises(SandboxError, match="escapes"):
        readonly.resolve(tmp_path.parent / "outside.txt")
    with pytest.raises(SandboxError, match="require full_access"):
        readonly.require_process_access()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_builtin_file_and_process_tools(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path, SandboxMode.FULL_ACCESS)
    tools = [
        file_write_tool(sandbox),
        file_read_tool(sandbox),
        file_search_tool(sandbox),
        python_tool(sandbox),
        shell_tool(sandbox),
    ]
    executor = ToolExecutor(ToolRegistry(tools))

    written = await executor.execute(
        _call("file_write", {"path": "nested/test.txt", "content": "hello"})
    )
    read = await executor.execute(_call("file_read", {"path": "nested/test.txt"}))
    found = await executor.execute(_call("file_search", {"pattern": "**/*.txt", "path": "."}))
    python = await executor.execute(_call("python", {"code": "print(6 * 7)"}))
    shell = await executor.execute(_call("shell", {"command": "echo harness"}))

    assert written.success
    assert read.output == "hello"
    assert "nested" in found.output and "test.txt" in found.output
    assert "42" in python.output
    assert "harness" in shell.output


@pytest.mark.integration
@pytest.mark.asyncio
async def test_process_cancellation_terminates_promptly(tmp_path: Path) -> None:
    sandbox = LocalSandbox(tmp_path)
    task = asyncio.create_task(
        sandbox.run_exec(
            [
                cast(str, __import__("sys").executable),
                "-c",
                "import time; time.sleep(30)",
            ]
        )
    )
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)
