"""Run a local Docker image when it is already installed; never pull implicitly."""

import asyncio
import subprocess
from pathlib import Path

from super_harness import DockerSandbox


async def main() -> None:
    sandbox = DockerSandbox(Path.cwd(), "alpine:3.20")
    available = sandbox.available() and subprocess.run(
        ["docker", "image", "inspect", "alpine:3.20"],
        capture_output=True,
        check=False,
    ).returncode == 0
    if not available:
        print("SKIP: Docker or local alpine:3.20 image is unavailable")
        return
    result = await sandbox.run_exec(("printf", "isolated"))
    print(result.stdout)


asyncio.run(main())

