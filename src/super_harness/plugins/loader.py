"""Super Harness and Codex-compatible plugin manifest loading."""

from __future__ import annotations

import json
import re
import tomllib
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, cast

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from super_harness.exceptions import PluginError
from super_harness.hooks import HookEvent, HookFailurePolicy

from .models import PluginHookSpec, PluginManifest

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def load_plugin(path: str | Path) -> PluginManifest:
    root = Path(path).resolve()
    harness = root / ".super-harness" / "plugin.toml"
    codex = root / ".codex-plugin" / "plugin.json"
    if harness.is_file():
        return _load_harness(root, harness)
    if codex.is_file():
        return _load_codex(root, codex)
    raise PluginError("plugin requires .super-harness/plugin.toml or .codex-plugin/plugin.json")


def _load_harness(root: Path, path: Path) -> PluginManifest:
    try:
        decoded = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PluginError("invalid Super Harness plugin manifest") from exc
    plugin_value = decoded.get("plugin")
    capabilities_value = decoded.get("capabilities", {})
    hooks_value = decoded.get("hooks", [])
    if not isinstance(plugin_value, dict) or not isinstance(capabilities_value, dict):
        raise PluginError("plugin manifest requires [plugin] and [capabilities] tables")
    if not isinstance(hooks_value, list):
        raise PluginError("plugin hooks must be an array of tables")
    plugin = cast(dict[str, Any], plugin_value)
    capabilities = cast(dict[str, Any], capabilities_value)
    known_root = {"plugin", "capabilities", "hooks"}
    warnings = [f"unsupported manifest field: {key}" for key in decoded if key not in known_root]
    warnings.extend(
        f"unsupported plugin field: {key}"
        for key in plugin
        if key not in {"name", "version", "description", "requires_super_harness"}
    )
    known_capabilities = {
        "skills",
        "tools",
        "mcp",
        "assets",
        "personas",
        "commands",
        "config_schema",
        "config_defaults",
    }
    warnings.extend(
        f"unsupported capability field: {key}"
        for key in capabilities
        if key not in known_capabilities
    )
    hook_values = cast(list[Any], hooks_value)
    hooks = tuple(
        _hook(root, cast(dict[str, Any], value)) for value in hook_values if isinstance(value, dict)
    )
    if len(hooks) != len(hook_values):
        raise PluginError("every plugin hook must be an object")
    manifest = PluginManifest(
        _name(plugin.get("name")),
        _version(plugin.get("version", "0.0.0")),
        str(plugin.get("description", "")).strip(),
        root,
        "super-harness",
        str(plugin.get("requires_super_harness", "")).strip(),
        _paths(root, capabilities.get("skills", []), "skills", directories=True),
        _entries(root, capabilities.get("tools", []), "tools"),
        _optional_path(root, capabilities.get("mcp"), "mcp"),
        None,
        hooks,
        _paths(root, capabilities.get("assets", []), "assets"),
        _paths(root, capabilities.get("personas", []), "personas"),
        _paths(root, capabilities.get("commands", []), "commands"),
        _optional_path(root, capabilities.get("config_schema"), "config_schema"),
        _optional_path(root, capabilities.get("config_defaults"), "config_defaults"),
        tuple(warnings),
        decoded,
    )
    _framework_compatible(manifest.requires_super_harness)
    return manifest


def _load_codex(root: Path, path: Path) -> PluginManifest:
    try:
        decoded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError("invalid Codex plugin manifest") from exc
    if not isinstance(decoded, dict):
        raise PluginError("Codex plugin manifest must be an object")
    raw = cast(dict[str, Any], decoded)
    known = {
        "$schema",
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "skills",
        "mcpServers",
        "hooks",
        "commands",
        "assets",
        "agents",
        "interface",
        "apps",
    }
    warnings = [f"unsupported Codex field: {key}" for key in raw if key not in known]
    skill_value = raw.get("skills", "./skills" if (root / "skills").is_dir() else [])
    mcp_value = raw.get("mcpServers")
    mcp_path: Path | None = None
    inline_mcp: dict[str, Any] | None = None
    if isinstance(mcp_value, str):
        mcp_path = _relative(root, mcp_value, "mcpServers")
    elif isinstance(mcp_value, dict):
        inline_mcp = {"mcpServers": mcp_value}
    elif mcp_value is None and (root / ".mcp.json").is_file():
        mcp_path = root / ".mcp.json"
    elif mcp_value is not None:
        warnings.append("unsupported Codex mcpServers shape")
    if raw.get("hooks") is not None:
        warnings.append("Codex command/MCP hooks are metadata-only and are not auto-executed")
    if raw.get("apps") is not None or raw.get("interface") is not None:
        warnings.append("Codex apps and interface metadata are retained but not activated")
    return PluginManifest(
        _name(raw.get("name") or root.name),
        _version(raw.get("version", "0.0.0")),
        str(raw.get("description", "")).strip(),
        root,
        "codex",
        skill_roots=_paths(root, skill_value, "skills", directories=True),
        mcp_path=mcp_path,
        inline_mcp=inline_mcp,
        assets=_paths(root, raw.get("assets", []), "assets"),
        personas=_paths(root, raw.get("agents", []), "agents"),
        commands=_paths(root, raw.get("commands", []), "commands"),
        warnings=tuple(warnings),
        extra=raw,
    )


def _hook(root: Path, raw: dict[str, Any]) -> PluginHookSpec:
    try:
        event = HookEvent(str(raw["event"]))
        entry = str(raw["entry"])
        failure = HookFailurePolicy(str(raw.get("failure_policy", "warn")))
    except (KeyError, ValueError) as exc:
        raise PluginError("invalid plugin hook event, entry, or failure policy") from exc
    _entry(root, entry, "hook")
    return PluginHookSpec(
        event,
        entry,
        str(raw["name"]) if raw.get("name") else None,
        int(raw.get("priority", 100)),
        float(raw.get("timeout", 10.0)),
        failure,
        bool(raw.get("allow_modify", False)),
    )


def _name(value: object) -> str:
    name = str(value or "").strip()
    if len(name) > 64 or not _NAME.fullmatch(name):
        raise PluginError("plugin name must be 1-64 lowercase kebab-case characters")
    return name


def _version(value: object) -> str:
    result = str(value).strip()
    try:
        Version(result)
    except InvalidVersion as exc:
        raise PluginError("plugin version is invalid") from exc
    return result


def _framework_compatible(specifier: str) -> None:
    if not specifier:
        return
    try:
        requirement = SpecifierSet(specifier)
        current = Version(package_version("super-harness"))
    except (InvalidSpecifier, InvalidVersion) as exc:
        raise PluginError("plugin framework version requirement is invalid") from exc
    if current not in requirement:
        raise PluginError(
            "plugin requires an incompatible Super Harness version",
            details={"required": specifier, "current": str(current)},
        )


def _entries(root: Path, value: object, field: str) -> tuple[str, ...]:
    values = _strings(value, field)
    for item in values:
        _entry(root, item, field)
    return values


def _entry(root: Path, value: str, field: str) -> None:
    path, separator, symbol = value.partition(":")
    if not separator or not symbol or not path.startswith("./") or not path.endswith(".py"):
        raise PluginError(f"plugin {field} entries require ./file.py:symbol")
    if not _relative(root, path, field).is_file():
        raise PluginError(f"plugin {field} entry module does not exist")


def _paths(root: Path, value: object, field: str, *, directories: bool = False) -> tuple[Path, ...]:
    paths = tuple(_relative(root, item, field) for item in _strings(value, field))
    for path in paths:
        if directories and not path.is_dir():
            raise PluginError(f"plugin {field} path must be a directory")
        if not directories and not path.exists():
            raise PluginError(f"plugin {field} path does not exist")
    return paths


def _optional_path(root: Path, value: object, field: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PluginError(f"plugin {field} must be a relative path")
    path = _relative(root, value, field)
    if not path.is_file():
        raise PluginError(f"plugin {field} path must be a file")
    return path


def _strings(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list):
        raise PluginError(f"plugin {field} must be a string or string array")
    values = cast(list[Any], value)
    if not all(isinstance(item, str) for item in values):
        raise PluginError(f"plugin {field} must be a string or string array")
    return tuple(cast(list[str], values))


def _relative(root: Path, value: str, field: str) -> Path:
    if not value.startswith("./") or ".." in Path(value).parts:
        raise PluginError(f"plugin {field} path must start with ./ and stay in plugin root")
    path = (root / value[2:]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PluginError(f"plugin {field} path escapes plugin root") from exc
    return path
