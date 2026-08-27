"""Super Harness diagnostics and ecosystem command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from super_harness import __version__
from super_harness.agent import Agent
from super_harness.cli_state import (
    CLIPaths,
    MCPConfigStore,
    public_mcp_data,
    registry_install_config,
)
from super_harness.config import ConfigResolver
from super_harness.exceptions import SuperHarnessError
from super_harness.mcp import (
    MCPServerConfig,
    MCPTransport,
    OfficialMCPRegistry,
    inspect_mcpb,
    install_mcpb,
)
from super_harness.models import DeepSeekProvider, Message, MessageRole, ModelRequest
from super_harness.models.openai_compatible import OpenAICompatibleProvider, WireAPI
from super_harness.observability import SecretRedactor
from super_harness.persistence import SQLiteThreadStore
from super_harness.plugins import PluginInstaller
from super_harness.skills import SkillInstaller


class CLIError(Exception):
    """Safe user-facing command error."""


class Output:
    def __init__(self, *, json_mode: bool = False) -> None:
        self.json_mode = json_mode
        self.redactor = SecretRedactor()

    def emit(self, value: object, *, message: str | None = None) -> None:
        safe: object = self.redactor.redact(value)
        if self.json_mode:
            print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
        elif message is not None:
            print(self.redactor.text(message))
        elif isinstance(safe, list):
            items = cast(list[object], safe)
            if not items:
                print("No entries.")
            for item in items:
                print(_human_line(item))
        elif isinstance(safe, dict):
            mapping = cast(dict[str, object], safe)
            for key, item in mapping.items():
                print(f"{key}: {_human_value(item)}")
        else:
            print(_human_value(safe))

    def error(self, error: BaseException) -> None:
        safe = self.redactor.redact(error)
        if self.json_mode:
            payload = {"ok": False, "error": safe}
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        else:
            print(f"error: {self.redactor.text(str(error))}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="super-harness")
    parser.add_argument("--version", action="version", version=f"super-harness {__version__}")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--global", dest="global_scope", action="store_true")
    scope.add_argument("--project", dest="global_scope", action="store_false")
    parser.set_defaults(global_scope=False)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("doctor", help="run local diagnostics")
    _skill_parser(commands)
    _mcp_parser(commands)
    _plugin_parser(commands)
    _thread_parser(commands)
    _provider_parser(commands)
    return parser


def _skill_parser(commands: Any) -> None:
    parser = commands.add_parser("skill", help="manage skills")
    actions = parser.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("source")
    actions.add_parser("list")
    info = actions.add_parser("info")
    info.add_argument("name")
    update = actions.add_parser("update")
    update.add_argument("name")
    remove = actions.add_parser("remove")
    remove.add_argument("name")


def _mcp_parser(commands: Any) -> None:
    parser = commands.add_parser("mcp", help="manage MCP servers")
    actions = parser.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("target")
    modes = add.add_mutually_exclusive_group()
    modes.add_argument("--stdio", action="store_true")
    modes.add_argument("--url")
    modes.add_argument("--registry", action="store_true")
    add.add_argument("--sha256")
    add.add_argument("--registry-url", default="https://registry.modelcontextprotocol.io")
    add.add_argument("server_command", nargs="*")
    actions.add_parser("list")
    inspect = actions.add_parser("inspect")
    inspect.add_argument("name")
    remove = actions.add_parser("remove")
    remove.add_argument("name")
    search = actions.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--registry-url", default="https://registry.modelcontextprotocol.io")
    imported = actions.add_parser("import")
    imported.add_argument("path")


def _plugin_parser(commands: Any) -> None:
    parser = commands.add_parser("plugin", help="manage plugins")
    actions = parser.add_subparsers(dest="action", required=True)
    add = actions.add_parser("add")
    add.add_argument("source")
    actions.add_parser("list")
    info = actions.add_parser("info")
    info.add_argument("name")
    update = actions.add_parser("update")
    update.add_argument("name")
    remove = actions.add_parser("remove")
    remove.add_argument("name")


def _thread_parser(commands: Any) -> None:
    parser = commands.add_parser("thread", help="inspect or resume durable threads")
    actions = parser.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser("inspect")
    inspect.add_argument("thread_id")
    inspect.add_argument("--show-content", action="store_true")
    inspect.add_argument("--database")
    resume = actions.add_parser("resume")
    resume.add_argument("thread_id")
    resume.add_argument("prompt")
    resume.add_argument("--database")
    _provider_options(resume)


def _provider_parser(commands: Any) -> None:
    parser = commands.add_parser("provider", help="test a model provider")
    actions = parser.add_subparsers(dest="action", required=True)
    test = actions.add_parser("test")
    test.add_argument("--prompt", default="Reply with exactly: OK")
    _provider_options(test)


def _provider_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--provider",
        choices=("deepseek", "openai-compatible"),
        default="deepseek",
    )
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key-env")
    parser.add_argument(
        "--wire-api",
        choices=(WireAPI.CHAT_COMPLETIONS.value, WireAPI.RESPONSES.value),
        default=WireAPI.CHAT_COMPLETIONS.value,
    )


def main(argv: Sequence[str] | None = None) -> int:
    if argv is None:
        print(f"super-harness {__version__}")
        return 0
    args = build_parser().parse_args(argv)
    output = Output(json_mode=bool(args.json))
    if args.command is None:
        output.emit({"name": "super-harness", "version": __version__})
        return 0
    paths = CLIPaths.resolve(Path.cwd(), global_scope=bool(args.global_scope))
    try:
        result, message = _dispatch(args, paths)
        output.emit(result, message=message)
        return 0
    except (CLIError, SuperHarnessError, KeyError, OSError, ValueError) as exc:
        output.error(exc)
        return 2


def _dispatch(args: argparse.Namespace, paths: CLIPaths) -> tuple[object, str | None]:
    if args.command == "doctor":
        return _doctor(paths), None
    if args.command == "skill":
        paths.ensure()
        return _skill(args, paths)
    if args.command == "mcp":
        paths.ensure()
        return _mcp(args, paths)
    if args.command == "plugin":
        paths.ensure()
        return _plugin(args, paths)
    if args.command == "thread":
        return _thread(args, paths)
    if args.command == "provider":
        return _provider(args), None
    raise CLIError(f"unknown command {args.command!r}")


def _doctor(paths: CLIPaths) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "status": "pass" if ok else "warn", "detail": detail})

    check("python", sys.version_info >= (3, 12), platform.python_version())
    check("git", shutil.which("git") is not None, shutil.which("git") or "not found")
    writable = paths.root.exists() and os.access(paths.root, os.W_OK)
    if not paths.root.exists():
        writable = paths.root.parent.exists() and os.access(paths.root.parent, os.W_OK)
    check("state_root", writable, str(paths.root))
    docker = shutil.which("docker")
    check("docker", docker is not None, docker or "not found")
    daemon = False
    if docker is not None:
        try:
            daemon = (
                subprocess.run(
                    [docker, "version", "--format", "{{.Server.Version}}"],
                    capture_output=True,
                    check=False,
                    timeout=3,
                ).returncode
                == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            daemon = False
    check("docker_daemon", daemon, "available" if daemon else "unavailable")
    check("mcp_sdk", importlib.util.find_spec("mcp") is not None, "optional dependency")
    check("opentelemetry", importlib.util.find_spec("opentelemetry") is not None, "optional")
    credential = bool(os.environ.get("DEEPSEEK_API_KEY"))
    check("deepseek_credential", credential, "configured" if credential else "not configured")
    try:
        resolved = ConfigResolver().resolve(cwd=paths.root.parent)
        config_detail = resolved.diagnostics()
        check("configuration", True, json.dumps(config_detail, ensure_ascii=False, default=str))
    except SuperHarnessError as exc:
        check("configuration", False, str(exc))
    if paths.mcp_config.exists():
        try:
            count = len(MCPConfigStore(paths.mcp_config).list())
            check("mcp_config", True, f"{count} server(s)")
        except SuperHarnessError as exc:
            check("mcp_config", False, str(exc))
    else:
        check("mcp_config", True, "not created")
    if paths.threads.exists():
        try:
            with SQLiteThreadStore(paths.threads) as store:
                count = len(store.ids(include_archived=True))
            check("thread_store", True, f"{count} thread(s)")
        except (OSError, RuntimeError) as exc:
            check("thread_store", False, str(exc))
    else:
        check("thread_store", True, "not created")
    return {
        "ok": all(item["status"] == "pass" for item in checks),
        "version": __version__,
        "scope": str(paths.root),
        "checks": checks,
    }


def _skill(args: argparse.Namespace, paths: CLIPaths) -> tuple[object, str | None]:
    installer = SkillInstaller(paths.skills)
    if args.action == "add":
        item = installer.install(args.source)
        return _skill_data(item, installer.info(item.name)[1]), f"Installed skill {item.name}."
    if args.action == "list":
        return [_skill_data(item) for item in installer.list()], None
    if args.action == "info":
        item, source = installer.info(args.name)
        return _skill_data(item, source), None
    if args.action == "update":
        item = installer.update(args.name)
        return _skill_data(item, installer.info(item.name)[1]), f"Updated skill {item.name}."
    installer.remove(args.name)
    return {"removed": args.name}, f"Removed skill {args.name}."


def _skill_data(item: Any, source: Any | None = None) -> dict[str, Any]:
    data = {
        "name": item.name,
        "description": item.description,
        "path": str(item.path),
        "source": item.source,
    }
    if source is not None:
        data["installation"] = asdict(source)
    return data


def _mcp(args: argparse.Namespace, paths: CLIPaths) -> tuple[object, str | None]:
    store = MCPConfigStore(paths.mcp_config)
    if args.action == "list":
        return [public_mcp_data(item) for item in store.list()], None
    if args.action == "inspect":
        return public_mcp_data(store.get(args.name)), None
    if args.action == "remove":
        store.remove(args.name)
        bundle = (paths.mcp_bundles / args.name).resolve()
        if bundle.is_dir() and bundle.parent == paths.mcp_bundles.resolve():
            shutil.rmtree(bundle)
        return {"removed": args.name}, f"Removed MCP server {args.name}."
    if args.action == "import":
        imported = store.import_file(args.path)
        return (
            [public_mcp_data(item) for item in imported],
            f"Imported {len(imported)} MCP server(s).",
        )
    if args.action == "search":
        registry = OfficialMCPRegistry(args.registry_url)
        results = asyncio.run(registry.search(args.query, limit=args.limit))
        return list(results), None
    config = _mcp_add_config(args, paths, store)
    store.add(config)
    return public_mcp_data(config), f"Added MCP server {config.name}."


def _mcp_add_config(
    args: argparse.Namespace, paths: CLIPaths, store: MCPConfigStore
) -> MCPServerConfig:
    target = Path(args.target)
    if target.suffix.casefold() == ".mcpb" and target.is_file():
        inspected = inspect_mcpb(target, expected_sha256=args.sha256)
        if any(item.name == inspected.name for item in store.list()):
            raise CLIError(f"MCP server {inspected.name!r} is already configured")
        return install_mcpb(
            target,
            paths.mcp_bundles,
            expected_sha256=args.sha256,
        ).config
    if args.url:
        return MCPServerConfig(
            args.target,
            MCPTransport.STREAMABLE_HTTP,
            url=args.url,
        )
    if args.stdio:
        command = list(args.server_command)
        if command and command[0] == "--":
            command.pop(0)
        if not command:
            raise CLIError("--stdio requires a command after --")
        return MCPServerConfig(
            args.target,
            MCPTransport.STDIO,
            command=command[0],
            args=tuple(command[1:]),
        )
    registry = OfficialMCPRegistry(args.registry_url)
    metadata = asyncio.run(registry.get(args.target))
    return registry_install_config(metadata)


def _plugin(args: argparse.Namespace, paths: CLIPaths) -> tuple[object, str | None]:
    installer = PluginInstaller(paths.plugins)
    if args.action == "add":
        item = installer.install(args.source)
        return _plugin_data(item), f"Installed plugin {item.manifest.name}."
    if args.action == "list":
        return [_manifest_data(item) for item in installer.list()], None
    if args.action == "info":
        return _plugin_data(installer.info(args.name)), None
    if args.action == "update":
        item = installer.update(args.name)
        return _plugin_data(item), f"Updated plugin {item.manifest.name}."
    installer.remove(args.name)
    return {"removed": args.name}, f"Removed plugin {args.name}."


def _manifest_data(manifest: Any) -> dict[str, Any]:
    return {
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "format": manifest.format,
        "warnings": list(manifest.warnings),
    }


def _plugin_data(installed: Any) -> dict[str, Any]:
    return {
        **_manifest_data(installed.manifest),
        "enabled": bool(installed.enabled),
        "source": dict(installed.source),
    }


def _thread(args: argparse.Namespace, paths: CLIPaths) -> tuple[object, str | None]:
    database = Path(args.database).resolve() if args.database else paths.threads
    if not database.is_file():
        raise CLIError(f"thread database does not exist: {database}")
    with SQLiteThreadStore(database) as store:
        if args.action == "inspect":
            snapshot = store.load(args.thread_id)
            return _snapshot_data(snapshot, show_content=args.show_content), None
        provider = _make_provider(args)
        try:
            thread = Agent(provider, store=store).resume(args.thread_id)
            response = thread.run(args.prompt)
        finally:
            asyncio.run(provider.aclose())
    return {
        "thread_id": args.thread_id,
        "response": response.text,
        "usage": asdict(response.usage),
    }, None


def _snapshot_data(snapshot: Any, *, show_content: bool) -> dict[str, Any]:
    messages = list(snapshot.messages)
    turns = list(snapshot.turns)
    data: dict[str, Any] = {
        "thread_id": snapshot.thread_id,
        "created_at": snapshot.created_at.isoformat(),
        "updated_at": snapshot.updated_at.isoformat(),
        "archived": snapshot.archived,
        "parent_thread_id": snapshot.parent_thread_id,
        "metadata": dict(snapshot.metadata),
        "message_count": len(messages),
        "turn_count": len(turns),
        "turn_statuses": [item.status.value for item in turns],
    }
    if show_content:
        data["messages"] = [{"role": item.role.value, "content": item.content} for item in messages]
    return data


def _provider(args: argparse.Namespace) -> dict[str, Any]:
    provider = _make_provider(args)
    try:
        response = asyncio.run(
            provider.complete(ModelRequest((Message(MessageRole.USER, args.prompt),)))
        )
    finally:
        asyncio.run(provider.aclose())
    return {
        "ok": True,
        "provider": provider.name,
        "model": provider.model,
        "response": response.text,
        "usage": asdict(response.usage),
    }


def _make_provider(args: argparse.Namespace) -> OpenAICompatibleProvider:
    wire_api = WireAPI(args.wire_api)
    if args.provider == "deepseek":
        return DeepSeekProvider(
            model=args.model or "deepseek-v4-flash",
            base_url=args.base_url or "https://api.deepseek.com",
            wire_api=wire_api,
            max_retries=0,
            stream_max_retries=0,
        )
    if not args.base_url or not args.model or not args.api_key_env:
        raise CLIError("openai-compatible requires --base-url, --model, and --api-key-env")
    return OpenAICompatibleProvider(
        model=args.model,
        base_url=args.base_url,
        api_key_env=args.api_key_env,
        wire_api=wire_api,
        max_retries=0,
        stream_max_retries=0,
    )


def _human_line(value: object) -> str:
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        preferred = ("name", "thread_id", "provider", "version")
        fields = [f"{key}={_human_value(mapping[key])}" for key in preferred if key in mapping]
        if fields:
            return "  ".join(fields)
        return _human_value(mapping)
    return _human_value(value)


def _human_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if value is None:
        return "-"
    return str(value)


def cli_entrypoint() -> int:
    """Parse process arguments for the installed console script."""
    return main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(cli_entrypoint())
