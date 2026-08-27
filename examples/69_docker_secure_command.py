"""Inspect the secure Docker command without starting a container."""

from pathlib import Path

from super_harness import DockerSandbox, SandboxMode

sandbox = DockerSandbox(Path.cwd(), "python:3.12-alpine", mode=SandboxMode.READ_ONLY)
command, _ = sandbox.build_command(("python", "-c", "print('isolated')"))
print(" ".join(command))

