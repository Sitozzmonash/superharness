"""Forward an allowlisted variable by name without placing its value in argv."""

from pathlib import Path

from super_harness import DockerSandbox

sandbox = DockerSandbox(Path.cwd(), "alpine:3.20", environment_allowlist=("APP_MODE",))
command, environment = sandbox.build_command(("sh", "-lc", "printf '%s' \"$APP_MODE\""), env={"APP_MODE": "test"})
print("APP_MODE" in command, "test" not in " ".join(command), environment["APP_MODE"])

