"""Typed MCP configuration and common mcpServers JSON import."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from super_harness.exceptions import MCPError


def _string_mapping() -> Mapping[str, str]:
    return {}


class MCPTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    transport: MCPTransport
    command: str | None = None
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=_string_mapping)
    cwd: Path | None = None
    url: str | None = None
    headers: Mapping[str, str] = field(default_factory=_string_mapping)
    timeout: float = 30.0
    enabled: bool = True
    include_tools: tuple[str, ...] = ()
    exclude_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip() or self.timeout <= 0:
            raise ValueError("MCP name must be non-empty and timeout positive")
        if self.transport is MCPTransport.STDIO and not self.command:
            raise ValueError("stdio MCP requires command")
        if self.transport is MCPTransport.STREAMABLE_HTTP and not self.url:
            raise ValueError("Streamable HTTP MCP requires url")
        object.__setattr__(self, "env", MappingProxyType(dict(self.env)))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))


def import_mcp_servers(value: str | Path | Mapping[str, Any]) -> tuple[MCPServerConfig, ...]:
    if isinstance(value, Mapping):
        decoded = value
    else:
        path = Path(value)
        try:
            candidate: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MCPError("unable to read MCP configuration") from exc
        if not isinstance(candidate, dict):
            raise MCPError("MCP configuration must be an object")
        decoded = cast(Mapping[str, Any], candidate)
    raw_servers = decoded.get("mcpServers")
    if not isinstance(raw_servers, dict):
        raise MCPError("MCP configuration requires mcpServers object")
    configs: list[MCPServerConfig] = []
    for name, raw_value in cast(dict[str, Any], raw_servers).items():
        if not isinstance(raw_value, dict):
            raise MCPError(f"MCP server {name!r} must be an object")
        raw = cast(dict[str, Any], raw_value)
        env_value = raw.get("env", {})
        headers_value = raw.get("headers", {})
        if not isinstance(env_value, dict) or not isinstance(headers_value, dict):
            raise MCPError(f"MCP server {name!r} env/headers must be objects")
        if raw.get("url"):
            configs.append(
                MCPServerConfig(
                    name,
                    MCPTransport.STREAMABLE_HTTP,
                    url=str(raw["url"]),
                    headers={
                        str(key): str(item)
                        for key, item in cast(dict[Any, Any], headers_value).items()
                    },
                    timeout=float(raw.get("timeout", 30.0)),
                    enabled=not bool(raw.get("disabled", False)),
                    include_tools=_strings(raw.get("includeTools", []), name, "includeTools"),
                    exclude_tools=_strings(raw.get("excludeTools", []), name, "excludeTools"),
                )
            )
        else:
            args_value = raw.get("args", [])
            if not isinstance(args_value, list):
                raise MCPError(f"MCP server {name!r} args must be a list")
            configs.append(
                MCPServerConfig(
                    name,
                    MCPTransport.STDIO,
                    command=str(raw.get("command", "")),
                    args=tuple(str(item) for item in cast(list[Any], args_value)),
                    env={
                        str(key): str(item) for key, item in cast(dict[Any, Any], env_value).items()
                    },
                    cwd=Path(str(raw["cwd"])) if raw.get("cwd") else None,
                    timeout=float(raw.get("timeout", 30.0)),
                    enabled=not bool(raw.get("disabled", False)),
                    include_tools=_strings(raw.get("includeTools", []), name, "includeTools"),
                    exclude_tools=_strings(raw.get("excludeTools", []), name, "excludeTools"),
                )
            )
    return tuple(configs)


def _strings(value: object, server: str, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise MCPError(f"MCP server {server!r} {field_name} must be a list")
    return tuple(str(item) for item in cast(list[Any], value))
