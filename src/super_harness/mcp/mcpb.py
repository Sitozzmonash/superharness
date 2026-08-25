"""Safe MCP Bundle validation and installation."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from super_harness.exceptions import MCPError

from .config import MCPServerConfig, MCPTransport

_MAX_FILES = 10_000
_MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class MCPBundle:
    name: str
    version: str
    manifest_version: str
    description: str
    config: MCPServerConfig


def inspect_mcpb(path: str | Path, *, expected_sha256: str | None = None) -> MCPBundle:
    bundle_path = Path(path)
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if expected_sha256 is not None and digest.casefold() != expected_sha256.casefold():
        raise MCPError("MCPB SHA-256 integrity check failed")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if len(names) != len(set(names)):
                raise MCPError("MCPB contains duplicate archive paths")
            if "manifest.json" not in names:
                raise MCPError("MCPB is missing manifest.json")
            total_size = sum(item.file_size for item in members)
            if len(members) > _MAX_FILES or total_size > _MAX_UNCOMPRESSED_BYTES:
                raise MCPError("MCPB exceeds archive safety limits")
            if any(_unsafe_member(name) for name in names):
                raise MCPError("MCPB contains an unsafe archive path")
            if any(_is_symlink(member) for member in members):
                raise MCPError("MCPB may not contain symbolic links")
            decoded: object = json.loads(archive.read("manifest.json"))
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        raise MCPError("invalid MCPB archive") from exc
    if not isinstance(decoded, dict):
        raise MCPError("MCPB manifest must be an object")
    manifest = cast(dict[str, Any], decoded)
    required = ("manifest_version", "name", "version", "description", "author", "server")
    if any(not manifest.get(key) for key in required):
        raise MCPError("MCPB manifest is missing required fields")
    name = str(manifest["name"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name):
        raise MCPError("MCPB name is not filesystem safe")
    server = manifest["server"]
    if not isinstance(server, dict):
        raise MCPError("MCPB server must be an object")
    server_data = cast(dict[str, Any], server)
    mcp_config_value = server_data.get("mcp_config", {})
    if not isinstance(mcp_config_value, dict):
        raise MCPError("MCPB mcp_config must be an object")
    mcp_config = cast(dict[str, Any], mcp_config_value)
    env_value = mcp_config.get("env", {})
    if not isinstance(env_value, dict):
        raise MCPError("MCPB mcp_config env must be an object")
    env = {str(key): str(value) for key, value in cast(dict[Any, Any], env_value).items()}
    command = str(mcp_config.get("command", "")).strip()
    args_value = mcp_config.get("args", [])
    if not isinstance(args_value, list):
        raise MCPError("MCPB mcp_config args must be a list")
    args = tuple(str(item) for item in cast(list[Any], args_value))
    if not command:
        server_type = str(server_data.get("type", ""))
        entry_point = str(server_data.get("entry_point", "")).strip()
        if not entry_point:
            raise MCPError("MCPB server requires an entry point or mcp_config command")
        if server_type == "uv":
            command, args = "uv", ("run", "${__dirname}/" + entry_point)
        elif server_type == "python":
            command, args = "python", ("${__dirname}/" + entry_point,)
        else:
            raise MCPError("MCPB server type requires an explicit mcp_config command")
    config = MCPServerConfig(name, MCPTransport.STDIO, command=command, args=args, env=env)
    return MCPBundle(
        name,
        str(manifest["version"]),
        str(manifest["manifest_version"]),
        str(manifest["description"]),
        config,
    )


def install_mcpb(
    path: str | Path, destination: str | Path, *, expected_sha256: str | None = None
) -> MCPBundle:
    bundle = inspect_mcpb(path, expected_sha256=expected_sha256)
    destination_path = Path(destination).resolve()
    target = (destination_path / bundle.name).resolve()
    try:
        target.relative_to(destination_path)
    except ValueError as exc:
        raise MCPError("MCPB name escapes installation root") from exc
    if target.exists():
        raise MCPError(f"MCP bundle {bundle.name!r} is already installed")
    with tempfile.TemporaryDirectory(prefix="super-harness-mcpb-") as temporary:
        staging = Path(temporary) / "bundle"
        with zipfile.ZipFile(path) as archive:
            archive.extractall(staging)
        shutil.copytree(staging, target)
    config = replace(
        bundle.config,
        command=_resolve_dir(bundle.config.command, target),
        args=tuple(_resolve_dir(item, target) for item in bundle.config.args),
        env={key: _resolve_dir(value, target) or "" for key, value in bundle.config.env.items()},
        cwd=target,
    )
    return replace(bundle, config=config)


def _unsafe_member(name: str) -> bool:
    path = Path(name)
    return path.is_absolute() or ".." in path.parts or bool(path.parts and ":" in path.parts[0])


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(member.external_attr >> 16)


def _resolve_dir(value: str | None, target: Path) -> str | None:
    if value is None:
        return None
    return value.replace("${__dirname}", str(target.resolve()))
