"""Explicit plugin capability activation and conflict management."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

from super_harness.exceptions import PluginError, SuperHarnessError
from super_harness.hooks import HookCallable, HookRegistry
from super_harness.mcp import MCPServerConfig, MCPTransport, import_mcp_servers
from super_harness.tools import Tool, ToolRegistry

from .installer import PluginInstaller
from .models import InstalledPlugin, PluginCapabilities, PluginManifest, PluginTrace


class PluginManager:
    def __init__(
        self,
        installer: PluginInstaller,
        *,
        tools: ToolRegistry | None = None,
        hooks: HookRegistry | None = None,
        trace_sink: Callable[[PluginTrace], None] | None = None,
    ) -> None:
        self.installer = installer
        self.tools = tools or ToolRegistry()
        self.hooks = hooks or HookRegistry()
        self.trace_sink = trace_sink
        self._enabled: dict[str, PluginCapabilities] = {}

    def install(self, source: str | Path) -> InstalledPlugin:
        installed = self.installer.install(source)
        self._trace(PluginTrace("install", installed.manifest.name, True))
        return installed

    def update(self, name: str) -> InstalledPlugin:
        if name in self._enabled:
            raise PluginError("disable a plugin before updating it")
        installed = self.installer.update(name)
        self._trace(PluginTrace("update", name, True))
        return installed

    def remove(self, name: str) -> None:
        if name in self._enabled:
            raise PluginError("disable a plugin before removing it")
        self.installer.remove(name)
        self._trace(PluginTrace("remove", name, True))

    def list(self) -> tuple[InstalledPlugin, ...]:
        return tuple(
            InstalledPlugin(
                item,
                item.name in self._enabled,
                self.installer.info(item.name).source,
            )
            for item in self.installer.list()
        )

    def info(self, name: str) -> InstalledPlugin:
        installed = self.installer.info(name)
        return InstalledPlugin(installed.manifest, name in self._enabled, installed.source)

    def enable(self, name: str) -> PluginCapabilities:
        if name in self._enabled:
            raise PluginError(f"plugin {name!r} is already enabled")
        manifest = self.installer.info(name).manifest
        try:
            tools = self._load_tools(manifest)
            mcp_servers = self._load_mcp(manifest)
        except PluginError as exc:
            self._trace(PluginTrace("enable", name, False, warning=str(exc)))
            raise
        except Exception as exc:
            self._trace(PluginTrace("enable", name, False, warning=type(exc).__name__))
            raise PluginError(f"plugin {name!r} capability loading failed") from exc
        registered_tools: list[str] = []
        registered_hooks: list[tuple[object, str]] = []
        source = f"plugin:{name}"
        try:
            for item in tools:
                self.tools.register(item)
                registered_tools.append(item.qualified_name)
            for spec in manifest.hook_specs:
                handler = self._symbol(manifest, spec.entry)
                if not callable(handler):
                    raise PluginError(f"plugin hook {spec.entry!r} is not callable")
                registration = self.hooks.register(
                    spec.event,
                    cast(HookCallable, handler),
                    name=spec.name,
                    source=source,
                    priority=spec.priority,
                    timeout=spec.timeout,
                    failure_policy=spec.failure_policy,
                    allow_modify=spec.allow_modify,
                )
                registered_hooks.append((spec.event, registration.name))
        except (SuperHarnessError, TypeError, ValueError) as exc:
            for tool_name in registered_tools:
                self.tools.unregister(tool_name)
            for event, hook_name in registered_hooks:
                self.hooks.unregister(cast(Any, event), hook_name, source=source)
            if isinstance(exc, PluginError):
                self._trace(PluginTrace("enable", name, False, warning=str(exc)))
                raise
            self._trace(PluginTrace("enable", name, False, warning=type(exc).__name__))
            raise PluginError(f"plugin {name!r} capability activation failed") from exc
        capabilities = PluginCapabilities(
            name,
            manifest.skill_roots,
            tools,
            mcp_servers,
            tuple(hook_name for _, hook_name in registered_hooks),
            manifest.assets,
            manifest.personas,
            manifest.commands,
        )
        self._enabled[name] = capabilities
        self._trace(
            PluginTrace(
                "enable",
                name,
                True,
                tuple(
                    key
                    for key, present in (
                        ("skills", bool(capabilities.skills)),
                        ("tools", bool(capabilities.tools)),
                        ("mcp", bool(capabilities.mcp_servers)),
                        ("hooks", bool(capabilities.hooks)),
                    )
                    if present
                ),
            )
        )
        return capabilities

    def disable(self, name: str) -> None:
        try:
            capabilities = self._enabled.pop(name)
        except KeyError as exc:
            raise PluginError(f"plugin {name!r} is not enabled") from exc
        for item in capabilities.tools:
            self.tools.unregister(item.qualified_name)
        source = f"plugin:{name}"
        manifest = self.installer.info(name).manifest
        for spec, hook_name in zip(manifest.hook_specs, capabilities.hooks, strict=True):
            self.hooks.unregister(spec.event, hook_name, source=source)
        self._trace(PluginTrace("disable", name, True))

    def capabilities(self) -> tuple[PluginCapabilities, ...]:
        return tuple(self._enabled.values())

    def _trace(self, trace: PluginTrace) -> None:
        if self.trace_sink is not None:
            self.trace_sink(trace)

    def _load_tools(self, manifest: PluginManifest) -> tuple[Tool, ...]:
        tools: list[Tool] = []
        for entry in manifest.tool_entries:
            value = self._symbol(manifest, entry)
            candidates: Iterable[object]
            if isinstance(value, Tool):
                candidates = (value,)
            elif isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
                candidates = cast(Iterable[object], value)
            else:
                raise PluginError(f"plugin tool entry {entry!r} does not export Tool values")
            for candidate in candidates:
                if not isinstance(candidate, Tool):
                    raise PluginError(f"plugin tool entry {entry!r} contains a non-Tool value")
                metadata = replace(
                    candidate.metadata,
                    namespace=manifest.name,
                    source=f"plugin:{manifest.name}",
                )
                tools.append(replace(candidate, metadata=metadata))
        names = [item.qualified_name for item in tools]
        if len(names) != len(set(names)):
            raise PluginError("plugin contains duplicate tool names")
        return tuple(tools)

    def _load_mcp(self, manifest: PluginManifest) -> tuple[MCPServerConfig, ...]:
        if manifest.mcp_path is not None:
            configs = import_mcp_servers(manifest.mcp_path)
        elif manifest.inline_mcp is not None:
            configs = import_mcp_servers(manifest.inline_mcp)
        else:
            return ()
        return tuple(
            replace(
                item,
                name=f"{manifest.name}.{item.name}",
                cwd=manifest.root if item.transport is MCPTransport.STDIO else item.cwd,
            )
            for item in configs
        )

    def _symbol(self, manifest: PluginManifest, entry: str) -> object:
        relative, _, symbol = entry.partition(":")
        path = (manifest.root / relative.removeprefix("./")).resolve()
        try:
            path.relative_to(manifest.root)
        except ValueError as exc:
            raise PluginError("plugin entry escapes plugin root") from exc
        if not path.is_file() or path.suffix != ".py":
            raise PluginError(f"plugin entry module {relative!r} does not exist")
        module = _module(path, manifest.name)
        try:
            return getattr(module, symbol)
        except AttributeError as exc:
            raise PluginError(f"plugin entry symbol {symbol!r} does not exist") from exc


def _module(path: Path, plugin: str) -> ModuleType:
    name = f"_super_harness_plugin_{plugin.replace('-', '_')}_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PluginError("unable to load plugin Python module")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise PluginError("plugin Python module execution failed") from exc
    return module
