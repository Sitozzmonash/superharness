"""Provider-neutral plugin manifest and capability values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from super_harness.hooks import HookEvent, HookFailurePolicy
from super_harness.mcp import MCPServerConfig
from super_harness.tools import Tool


def _extra() -> Mapping[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class PluginHookSpec:
    event: HookEvent
    entry: str
    name: str | None = None
    priority: int = 100
    timeout: float = 10.0
    failure_policy: HookFailurePolicy = HookFailurePolicy.WARN
    allow_modify: bool = False


@dataclass(frozen=True, slots=True)
class PluginManifest:
    name: str
    version: str
    description: str
    root: Path
    format: str
    requires_super_harness: str = ""
    skill_roots: tuple[Path, ...] = ()
    tool_entries: tuple[str, ...] = ()
    mcp_path: Path | None = None
    inline_mcp: Mapping[str, Any] | None = None
    hook_specs: tuple[PluginHookSpec, ...] = ()
    assets: tuple[Path, ...] = ()
    personas: tuple[Path, ...] = ()
    commands: tuple[Path, ...] = ()
    config_schema: Path | None = None
    config_defaults: Path | None = None
    warnings: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=_extra)

    def __post_init__(self) -> None:
        if self.inline_mcp is not None:
            object.__setattr__(self, "inline_mcp", MappingProxyType(dict(self.inline_mcp)))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


@dataclass(frozen=True, slots=True)
class PluginCapabilities:
    plugin: str
    skills: tuple[Path, ...] = ()
    tools: tuple[Tool, ...] = ()
    mcp_servers: tuple[MCPServerConfig, ...] = ()
    hooks: tuple[str, ...] = ()
    assets: tuple[Path, ...] = ()
    personas: tuple[Path, ...] = ()
    commands: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class InstalledPlugin:
    manifest: PluginManifest
    enabled: bool
    source: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", MappingProxyType(dict(self.source)))


@dataclass(frozen=True, slots=True)
class PluginTrace:
    operation: str
    plugin: str
    success: bool
    capabilities: tuple[str, ...] = ()
    warning: str | None = None
