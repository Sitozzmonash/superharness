"""Local workspace path policy and cancellable subprocess execution."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from super_harness.exceptions import SandboxError


class SandboxMode(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str


def _default_environment_names() -> tuple[str, ...]:
    return (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
    )


@dataclass(slots=True)
class LocalSandbox:
    """A path-constrained local runner, not a strong security boundary."""

    workspace: Path
    mode: SandboxMode = SandboxMode.FULL_ACCESS
    environment_allowlist: tuple[str, ...] = field(default_factory=_default_environment_names)

    def __post_init__(self) -> None:
        self.workspace = self.workspace.resolve(strict=True)
        if not self.workspace.is_dir():
            raise SandboxError("sandbox workspace must be a directory")

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    def resolve(self, path: str | Path, *, write: bool = False) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve(strict=False)
        if self.mode is not SandboxMode.FULL_ACCESS and not self._within(resolved, self.workspace):
            raise SandboxError(
                "path escapes sandbox workspace",
                details={"workspace": str(self.workspace), "path": str(resolved)},
            )
        if write and self.mode is SandboxMode.READ_ONLY:
            raise SandboxError("sandbox is read-only", details={"path": str(resolved)})
        return resolved

    def process_environment(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        environment = {
            name: value
            for name in self.environment_allowlist
            if (value := os.environ.get(name)) is not None
        }
        environment.update(extra or {})
        return environment

    def require_process_access(self) -> None:
        if self.mode is not SandboxMode.FULL_ACCESS:
            raise SandboxError(
                "local shell and Python processes require full_access because the local "
                "runner is not a strong isolation boundary"
            )

    async def run_exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        self.require_process_access()
        if not argv:
            raise SandboxError("process argv must be non-empty")
        process_cwd = self.resolve(cwd or self.workspace)
        if os.name == "nt":
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=process_cwd,
                env=self.process_environment(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=process_cwd,
                env=self.process_environment(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        return ProcessResult(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def run_shell(
        self,
        command: str,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        self.require_process_access()
        process_cwd = self.resolve(cwd or self.workspace)
        if os.name == "nt":
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=process_cwd,
                env=self.process_environment(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=0x00000200,
            )
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=process_cwd,
                env=self.process_environment(env),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        return ProcessResult(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
