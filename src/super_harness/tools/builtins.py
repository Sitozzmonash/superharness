"""Basic sandbox-aware file, shell, and Python tools."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import cast

from .definition import Tool, tool
from .sandbox import LocalSandbox


def _built(candidate: Tool | object) -> Tool:
    return cast(Tool, candidate)


def file_read_tool(sandbox: LocalSandbox) -> Tool:
    @tool(name="file_read", source="builtin", risk="low", supports_parallel=True)
    async def file_read(path: str) -> str:
        """Read one UTF-8 text file from the allowed workspace."""

        resolved = sandbox.resolve(path)
        return await asyncio.to_thread(resolved.read_text, encoding="utf-8")

    return _built(file_read)


def file_write_tool(sandbox: LocalSandbox) -> Tool:
    @tool(name="file_write", source="builtin", risk="write")
    async def file_write(path: str, content: str) -> dict[str, object]:
        """Write one UTF-8 text file inside the allowed workspace."""

        resolved = sandbox.resolve(path, write=True)
        await asyncio.to_thread(resolved.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(resolved.write_text, content, encoding="utf-8")
        return {"path": str(resolved), "characters": len(content)}

    return _built(file_write)


def file_search_tool(sandbox: LocalSandbox) -> Tool:
    @tool(name="file_search", source="builtin", risk="low", supports_parallel=True)
    async def file_search(pattern: str, path: str = ".") -> list[str]:
        """Find workspace files by a glob pattern."""

        root = sandbox.resolve(path)

        def search() -> list[str]:
            return [
                str(candidate.relative_to(sandbox.workspace))
                for candidate in sorted(root.glob(pattern))
                if candidate.is_file()
            ]

        return await asyncio.to_thread(search)

    return _built(file_search)


def shell_tool(sandbox: LocalSandbox) -> Tool:
    @tool(name="shell", source="builtin", risk="process", timeout=60.0)
    async def shell(command: str, cwd: str = ".") -> dict[str, object]:
        """Run a shell command in the local full-access sandbox."""

        result = await sandbox.run_shell(command, cwd=cwd)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    return _built(shell)


def python_tool(sandbox: LocalSandbox) -> Tool:
    @tool(name="python", source="builtin", risk="process", timeout=60.0)
    async def python(code: str, cwd: str = ".") -> dict[str, object]:
        """Run Python code in a child process in the local full-access sandbox."""

        result = await sandbox.run_exec([sys.executable, "-c", code], cwd=cwd)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    return _built(python)


def basic_builtin_tools(workspace: str | Path) -> tuple[Tool, ...]:
    sandbox = LocalSandbox(Path(workspace))
    return (
        file_read_tool(sandbox),
        file_write_tool(sandbox),
        file_search_tool(sandbox),
        shell_tool(sandbox),
        python_tool(sandbox),
    )
