"""Resolve a built-in credential-free profile."""

from super_harness import ConfigResolver

resolved = ConfigResolver(user_config="missing.toml").resolve(
    environment={"SUPER_HARNESS_PROFILE": "offline"}
)
print(resolved.diagnostics())

