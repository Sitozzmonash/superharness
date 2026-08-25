"""Exercise sandbox-aware file and Python built-ins locally."""

import asyncio
import tempfile
from pathlib import Path

from super_harness import LocalSandbox, ToolExecutor, ToolRegistry
from super_harness.models import ToolCall
from super_harness.tools import file_read_tool, file_write_tool, python_tool


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        sandbox = LocalSandbox(Path(directory))
        registry = ToolRegistry(
            [file_write_tool(sandbox), file_read_tool(sandbox), python_tool(sandbox)]
        )
        executor = ToolExecutor(registry)
        write = ToolCall(
            "write_1",
            "file_write",
            {"path": "answer.txt", "content": "42"},
            '{"path":"answer.txt","content":"42"}',
        )
        read = ToolCall("read_1", "file_read", {"path": "answer.txt"}, '{"path":"answer.txt"}')
        run = ToolCall("python_1", "python", {"code": "print(6 * 7)"}, '{"code":"print(6 * 7)"}')
        print(await executor.execute(write))
        print(await executor.execute(read))
        print(await executor.execute(run))


if __name__ == "__main__":
    asyncio.run(main())
