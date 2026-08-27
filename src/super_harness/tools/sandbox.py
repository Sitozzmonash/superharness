"""Local workspace path policy and cancellable subprocess execution."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

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


def _mount_mapping() -> Mapping[Path, str]:
    return {}


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
            await asyncio.shield(asyncio.create_task(self.terminate(process)))
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
            await asyncio.shield(asyncio.create_task(self.terminate(process)))
            raise
        return ProcessResult(
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    @staticmethod
    async def terminate(process: asyncio.subprocess.Process) -> None:
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
            try:
                async with asyncio.timeout(2.0):
                    await killer.wait()
            except TimeoutError:
                killer.kill()
                await killer.wait()
            if process.returncode is None:
                process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


@dataclass(slots=True)
class DockerSandbox:
    """Bounded Docker CLI backend with secure isolation defaults."""

    workspace: Path
    image: str
    mode: SandboxMode = SandboxMode.WORKSPACE_WRITE
    network: str = "none"
    environment_allowlist: tuple[str, ...] = ()
    read_only_mounts: Mapping[Path, str] = field(default_factory=_mount_mapping)
    cpus: float = 1.0
    memory: str = "512m"
    pids_limit: int = 128
    timeout: float = 60.0
    docker_executable: str = "docker"

    def __post_init__(self) -> None:
        self.workspace = self.workspace.resolve(strict=True)
        if not self.workspace.is_dir():
            raise SandboxError("Docker workspace must be a directory")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]{0,255}", self.image):
            raise SandboxError("Docker image reference is invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.network):
            raise SandboxError("Docker network mode is invalid")
        if not 0 < self.cpus <= 64 or not 16 <= self.pids_limit <= 4096 or self.timeout <= 0:
            raise SandboxError("Docker resource limits are invalid")
        if not re.fullmatch(r"[1-9][0-9]*[kKmMgG]", self.memory):
            raise SandboxError("Docker memory limit must use a k/m/g suffix")
        mounts: dict[Path, str] = {}
        for source, target in self.read_only_mounts.items():
            resolved = Path(source).resolve(strict=True)
            if not target.startswith("/") or ".." in Path(target).parts:
                raise SandboxError("Docker mount target must be an absolute safe path")
            mounts[resolved] = target
        self.read_only_mounts = mounts

    def available(self) -> bool:
        return shutil.which(self.docker_executable) is not None

    def describe(self) -> dict[str, object]:
        return {
            "backend": "docker",
            "image": self.image,
            "mode": self.mode.value,
            "network": self.network,
            "read_only_root": True,
            "capabilities_dropped": True,
            "cpus": self.cpus,
            "memory": self.memory,
            "pids_limit": self.pids_limit,
            "timeout": self.timeout,
        }

    def build_command(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        container_name: str | None = None,
    ) -> tuple[list[str], dict[str, str]]:
        if not argv or any("\x00" in item for item in argv):
            raise SandboxError("Docker process argv must be non-empty and contain no NUL")
        name = container_name or f"super-harness-{uuid4().hex}"
        process_cwd = Path(cwd or self.workspace).resolve(strict=False)
        try:
            relative_cwd = process_cwd.relative_to(self.workspace)
        except ValueError as exc:
            raise SandboxError("Docker cwd escapes workspace") from exc
        environment = {
            key: value
            for key in self.environment_allowlist
            if (value := os.environ.get(key)) is not None
        }
        for key, value in (env or {}).items():
            if key not in self.environment_allowlist:
                raise SandboxError(
                    "Docker environment key is not allowlisted",
                    details={"key": key},
                )
            environment[key] = value
        mount_mode = "ro" if self.mode is SandboxMode.READ_ONLY else "rw"
        command = [
            self.docker_executable,
            "run",
            "--rm",
            "--init",
            "--name",
            name,
            "--network",
            self.network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            self.memory,
            "--cpus",
            str(self.cpus),
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--mount",
            f"type=bind,src={self.workspace},dst=/workspace,{mount_mode}",
            "--workdir",
            "/workspace/" + relative_cwd.as_posix(),
        ]
        for source, target in self.read_only_mounts.items():
            command.extend(["--mount", f"type=bind,src={source},dst={target},readonly"])
        for key in sorted(environment):
            command.extend(["--env", key])
        command.extend([self.image, *argv])
        process_environment = LocalSandbox(self.workspace).process_environment(environment)
        return command, process_environment

    async def run_exec(
        self,
        argv: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        name = f"super-harness-{uuid4().hex}"
        command, environment = self.build_command(
            argv,
            cwd=cwd,
            env=env,
            container_name=name,
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise SandboxError("Docker executable is unavailable") from exc
        try:
            async with asyncio.timeout(self.timeout):
                stdout, stderr = await process.communicate()
        except (TimeoutError, asyncio.CancelledError):
            await asyncio.shield(asyncio.create_task(self._cleanup(name, environment)))
            await asyncio.shield(asyncio.create_task(LocalSandbox.terminate(process)))
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
        return await self.run_exec(("/bin/sh", "-lc", command), cwd=cwd, env=env)

    async def _cleanup(self, name: str, environment: Mapping[str, str]) -> None:
        try:
            cleanup = await asyncio.create_subprocess_exec(
                self.docker_executable,
                "rm",
                "-f",
                name,
                env=environment,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                async with asyncio.timeout(3.0):
                    await cleanup.wait()
            except TimeoutError:
                cleanup.kill()
                await cleanup.wait()
        except OSError:
            return
