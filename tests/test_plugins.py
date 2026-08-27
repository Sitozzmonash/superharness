from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from super_harness import (
    HookRegistry,
    PluginInstaller,
    PluginManager,
    PluginTrace,
    ToolExecutor,
    ToolRegistry,
    load_plugin,
    tool,
)
from super_harness.exceptions import PluginError, ToolError
from super_harness.models import ToolCall

PINNED_OPENAI_PLUGINS = "11c74d6ba24d3a6d48f54a194cd00ef3beea18f9"


def _plugin(root: Path, *, version: str = "1.0.0", incompatible: bool = False) -> Path:
    plugin = root / "demo-plugin"
    (plugin / ".super-harness").mkdir(parents=True)
    (plugin / "skills" / "demo-skill").mkdir(parents=True)
    (plugin / "skills" / "demo-skill" / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Demo\n---\nDo the demo.", encoding="utf-8"
    )
    (plugin / "mcp.json").write_text(
        json.dumps({"mcpServers": {"demo": {"command": "python", "args": ["server.py"]}}}),
        encoding="utf-8",
    )
    (plugin / "extension.py").write_text(
        """from super_harness import HookResult, tool

@tool
def echo(text: str) -> str:
    return text

TOOLS = [echo]

def uppercase(context):
    arguments = dict(context.data["arguments"])
    arguments["text"] = arguments["text"].upper()
    return HookResult.enrich(arguments=arguments)
""",
        encoding="utf-8",
    )
    requirement = ">=99" if incompatible else ">=0.0.1.dev0,<1"
    (plugin / ".super-harness" / "plugin.toml").write_text(
        f"""[plugin]
name = "demo-plugin"
version = "{version}"
description = "Demo capability bundle"
requires_super_harness = "{requirement}"

[capabilities]
skills = ["./skills"]
tools = ["./extension.py:TOOLS"]
mcp = "./mcp.json"

[[hooks]]
event = "pre_tool_use"
entry = "./extension.py:uppercase"
failure_policy = "fail_closed"
allow_modify = true
""",
        encoding="utf-8",
    )
    return plugin


@pytest.mark.integration
@pytest.mark.asyncio
async def test_plugin_install_enable_bundle_disable_update_and_remove(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "source")
    tools = ToolRegistry()
    hooks = HookRegistry()
    traces: list[PluginTrace] = []
    manager = PluginManager(
        PluginInstaller(tmp_path / "installed"),
        tools=tools,
        hooks=hooks,
        trace_sink=traces.append,
    )

    installed = manager.install(source)
    assert installed.manifest.name == "demo-plugin"
    assert not installed.enabled
    capabilities = manager.enable("demo-plugin")
    assert len(capabilities.skills) == 1
    assert [item.name for item in capabilities.mcp_servers] == ["demo-plugin.demo"]
    assert capabilities.hooks == ("uppercase",)

    executor = ToolExecutor(tools, hooks=hooks)
    call = ToolCall("call_1", "demo-plugin.echo", {"text": "hello"}, '{"text":"hello"}')
    result = await executor.execute(call)
    assert result.success and result.output == "HELLO"

    manager.disable("demo-plugin")
    with pytest.raises(ToolError, match="unknown"):
        tools.get("demo-plugin.echo")
    (source / ".super-harness" / "plugin.toml").write_text(
        (source / ".super-harness" / "plugin.toml")
        .read_text(encoding="utf-8")
        .replace('version = "1.0.0"', 'version = "1.1.0"'),
        encoding="utf-8",
    )
    assert manager.update("demo-plugin").manifest.version == "1.1.0"
    manager.remove("demo-plugin")
    assert manager.list() == ()
    assert [trace.operation for trace in traces] == [
        "install",
        "enable",
        "disable",
        "update",
        "remove",
    ]


def test_plugin_validation_codex_import_conflicts_and_no_auto_execution(tmp_path: Path) -> None:
    source = _plugin(tmp_path / "source")
    marker = source / "executed"
    extension = source / "extension.py"
    marker_code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('yes')\n"
    extension.write_text(
        marker_code + extension.read_text(),
        encoding="utf-8",
    )
    installer = PluginInstaller(tmp_path / "installed")
    installer.install(source)
    assert not marker.exists()

    conflicting = ToolRegistry()
    hooks = HookRegistry()
    manager = PluginManager(installer, tools=conflicting, hooks=hooks)
    capabilities = manager.enable("demo-plugin")
    assert capabilities.tools
    assert marker.is_file()
    manager.disable("demo-plugin")

    @tool(namespace="demo-plugin")
    def echo(text: str) -> str:
        return text

    conflicting.register(echo)
    with pytest.raises(PluginError, match="activation failed"):
        manager.enable("demo-plugin")
    assert hooks.list() == ()

    incompatible = _plugin(tmp_path / "bad", incompatible=True)
    with pytest.raises(PluginError, match="incompatible"):
        load_plugin(incompatible)

    unsafe = _plugin(tmp_path / "unsafe")
    manifest_path = unsafe / ".super-harness" / "plugin.toml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace("./skills", "./../outside"),
        encoding="utf-8",
    )
    with pytest.raises(PluginError, match="stay in plugin root"):
        load_plugin(unsafe)

    codex = tmp_path / "codex"
    (codex / ".codex-plugin").mkdir(parents=True)
    (codex / "skills" / "one").mkdir(parents=True)
    (codex / ".codex-plugin" / "plugin.json").write_text(
        json.dumps({"name": "codex-demo", "version": "2.0.0", "skills": "./skills"}),
        encoding="utf-8",
    )
    imported = load_plugin(codex)
    assert imported.format == "codex"
    assert imported.skill_roots == (codex / "skills",)


@pytest.mark.e2e
def test_official_codex_plugin_repository_compatibility(tmp_path: Path) -> None:
    if os.environ.get("SUPER_HARNESS_EXTERNAL_COMPAT") != "1":
        pytest.skip("set SUPER_HARNESS_EXTERNAL_COMPAT=1 for official plugin E2E")
    source = f"https://github.com/openai/plugins/tree/{PINNED_OPENAI_PLUGINS}/plugins/plugin-eval"
    installed = PluginInstaller(tmp_path / "installed").install(source)
    assert installed.manifest.format == "codex"
    assert installed.manifest.name == "plugin-eval"
    assert installed.manifest.skill_roots
