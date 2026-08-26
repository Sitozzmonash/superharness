"""Scoped, atomic CLI state helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from super_harness.exceptions import MCPError
from super_harness.mcp import MCPServerConfig, MCPTransport, import_mcp_servers


@dataclass(frozen=True, slots=True)
class CLIPaths:
    root: Path
    skills: Path
    plugins: Path
    mcp_bundles: Path
    mcp_config: Path
    threads: Path

    @classmethod
    def resolve(cls, cwd: str | Path, *, global_scope: bool = False) -> CLIPaths:
        if global_scope:
            root = Path(os.environ.get("SUPER_HARNESS_HOME", Path.home() / ".super-harness"))
        else:
            project = _project_root(Path(cwd).resolve())
            root = project / ".super-harness"
        root = root.resolve()
        return cls(
            root,
            root / "skills",
            root / "plugins",
            root / "mcp-bundles",
            root / "mcp.json",
            root / "threads.db",
        )

    def ensure(self) -> None:
        for path in (self.root, self.skills, self.plugins, self.mcp_bundles):
            path.mkdir(parents=True, exist_ok=True)


class MCPConfigStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list(self) -> tuple[MCPServerConfig, ...]:
        if not self.path.exists():
            return ()
        return import_mcp_servers(self.path)

    def get(self, name: str) -> MCPServerConfig:
        for config in self.list():
            if config.name == name:
                return config
        raise MCPError(f"MCP server {name!r} is not configured")

    def add(self, config: MCPServerConfig) -> None:
        configs = list(self.list())
        if any(item.name == config.name for item in configs):
            raise MCPError(f"MCP server {config.name!r} is already configured")
        configs.append(config)
        self._write(configs)

    def import_file(self, path: str | Path) -> tuple[MCPServerConfig, ...]:
        imported = import_mcp_servers(path)
        configs = list(self.list())
        names = {item.name for item in configs}
        duplicates = sorted(item.name for item in imported if item.name in names)
        if duplicates:
            raise MCPError("MCP import contains configured names", details={"names": duplicates})
        configs.extend(imported)
        self._write(configs)
        return imported

    def remove(self, name: str) -> None:
        configs = list(self.list())
        retained = [item for item in configs if item.name != name]
        if len(retained) == len(configs):
            raise MCPError(f"MCP server {name!r} is not configured")
        self._write(retained)

    def _write(self, configs: list[MCPServerConfig]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"mcpServers": {item.name: _mcp_data(item) for item in configs}}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(self.path)


def public_mcp_data(config: MCPServerConfig) -> dict[str, Any]:
    """Return MCP metadata without secret-bearing values."""
    data: dict[str, Any] = {
        "name": config.name,
        "transport": config.transport.value,
        "enabled": config.enabled,
        "timeout": config.timeout,
        "include_tools": list(config.include_tools),
        "exclude_tools": list(config.exclude_tools),
    }
    if config.transport is MCPTransport.STDIO:
        data.update(
            {
                "command": config.command,
                "args": list(config.args),
                "cwd": str(config.cwd) if config.cwd else None,
                "env_keys": sorted(config.env),
            }
        )
    else:
        data.update({"url": config.url, "header_keys": sorted(config.headers)})
    return data


def _mcp_data(config: MCPServerConfig) -> dict[str, Any]:
    common: dict[str, Any] = {
        "timeout": config.timeout,
        "disabled": not config.enabled,
        "includeTools": list(config.include_tools),
        "excludeTools": list(config.exclude_tools),
    }
    if config.transport is MCPTransport.STDIO:
        common.update(
            {
                "command": config.command,
                "args": list(config.args),
                "env": dict(config.env),
                "cwd": str(config.cwd) if config.cwd else None,
            }
        )
    else:
        common.update({"url": config.url, "headers": dict(config.headers)})
    return {key: value for key, value in common.items() if value not in (None, [], {})}


def registry_install_config(value: object) -> MCPServerConfig:
    """Resolve standardized registry metadata into one supported MCP configuration."""
    if not isinstance(value, dict):
        raise MCPError("registry server metadata must be an object")
    metadata = cast(dict[str, Any], value)
    server = metadata.get("server") if isinstance(metadata.get("server"), dict) else metadata
    server_data = cast(dict[str, Any], server)
    name = str(server_data.get("name") or metadata.get("name") or "").strip()
    remotes_value: object = server_data.get("remotes") or metadata.get("remotes") or []
    if name and isinstance(remotes_value, list):
        for remote in cast(list[object], remotes_value):
            if isinstance(remote, dict):
                remote_data = cast(dict[str, Any], remote)
                if remote_data.get("url"):
                    return MCPServerConfig(
                        name,
                        MCPTransport.STREAMABLE_HTTP,
                        url=str(remote_data["url"]),
                    )
    packages_value: object = server_data.get("packages") or metadata.get("packages") or []
    if name and isinstance(packages_value, list):
        for package in cast(list[object], packages_value):
            if not isinstance(package, dict):
                continue
            package_data = cast(dict[str, Any], package)
            identifier = str(package_data.get("identifier") or "").strip()
            registry_type = str(package_data.get("registryType") or "").casefold()
            if registry_type == "npm" and identifier:
                return MCPServerConfig(
                    name,
                    MCPTransport.STDIO,
                    command="npx",
                    args=("-y", identifier),
                )
            if registry_type in {"pypi", "python"} and identifier:
                return MCPServerConfig(
                    name,
                    MCPTransport.STDIO,
                    command="uvx",
                    args=(identifier,),
                )
    raise MCPError("registry entry has no supported remote or package installation metadata")


def _project_root(cwd: Path) -> Path:
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd
