from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from super_harness import Agent, SQLiteThreadStore
from super_harness import cli as cli_module
from super_harness.cli import main
from super_harness.cli_state import CLIPaths, MCPConfigStore, registry_install_config
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)


class EchoProvider:
    name = "echo"
    model = "echo-1"
    capabilities = ModelCapabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("ok")

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=ModelResponse("ok"))

    async def aclose(self) -> None:
        return None


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _json(capsys: pytest.CaptureFixture[str]) -> Any:
    return json.loads(capsys.readouterr().out)


def _skill(root: Path, *, description: str = "Demo skill") -> Path:
    source = root / "demo-skill"
    source.mkdir(parents=True, exist_ok=True)
    (source / "SKILL.md").write_text(
        f"---\nname: demo-skill\ndescription: {description}\n---\nUse the demo.",
        encoding="utf-8",
    )
    return source


def _plugin(root: Path, *, version: str = "1.0.0") -> Path:
    source = root / "demo-plugin"
    (source / ".super-harness").mkdir(parents=True)
    (source / ".super-harness" / "plugin.toml").write_text(
        f'''[plugin]
name = "demo-plugin"
version = "{version}"
description = "Demo plugin"
requires_super_harness = ">=0.0.1.dev0,<1"
''',
        encoding="utf-8",
    )
    return source


def _bundle(path: Path) -> str:
    manifest = {
        "manifest_version": "0.3",
        "name": "demo-bundle",
        "version": "1.0.0",
        "description": "Demo bundle",
        "author": {"name": "Tester"},
        "server": {
            "type": "python",
            "entry_point": "server.py",
            "mcp_config": {
                "command": "python",
                "args": ["${__dirname}/server.py"],
            },
        },
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("server.py", "print('server')")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_version_help_and_doctor_json(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "doctor"]) == 0
    result = _json(capsys)
    assert result["version"] == "0.0.1.dev0"
    assert {item["name"] for item in result["checks"]} >= {"python", "git", "thread_store"}
    assert str(project / ".super-harness") == result["scope"]


def test_skill_full_lifecycle(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _skill(project / "sources")
    assert main(["--json", "skill", "add", str(source)]) == 0
    assert _json(capsys)["name"] == "demo-skill"
    assert main(["--json", "skill", "list"]) == 0
    assert _json(capsys)[0]["name"] == "demo-skill"
    source.joinpath("SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Updated\n---\nUse it.", encoding="utf-8"
    )
    assert main(["--json", "skill", "update", "demo-skill"]) == 0
    assert _json(capsys)["description"] == "Updated"
    assert main(["--json", "skill", "info", "demo-skill"]) == 0
    assert _json(capsys)["installation"]["source_type"] == "local"
    assert main(["--json", "skill", "remove", "demo-skill"]) == 0
    assert _json(capsys)["removed"] == "demo-skill"


def test_mcp_stdio_remote_import_inspect_remove_and_redaction(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "mcp", "add", "local", "--stdio", "--", "python", "server.py"]) == 0
    assert _json(capsys)["command"] == "python"
    assert main(["--json", "mcp", "add", "remote", "--url", "https://example.test/mcp"]) == 0
    assert _json(capsys)["transport"] == "streamable_http"
    config = project / "import.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "secret-server": {
                        "command": "python",
                        "env": {"API_KEY": "sk-abcdefghijklmnop"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert main(["--json", "mcp", "import", str(config)]) == 0
    output = capsys.readouterr().out
    assert "sk-abcdefghijklmnop" not in output
    assert '"env_keys"' in output
    assert main(["--json", "mcp", "inspect", "secret-server"]) == 0
    assert _json(capsys)["env_keys"] == ["API_KEY"]
    assert main(["--json", "mcp", "remove", "local"]) == 0
    assert _json(capsys)["removed"] == "local"


def test_mcp_bundle_integrity_install_and_cleanup(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = project / "demo.mcpb"
    digest = _bundle(bundle)
    assert main(["--json", "mcp", "add", str(bundle), "--sha256", digest]) == 0
    assert _json(capsys)["name"] == "demo-bundle"
    installed = project / ".super-harness" / "mcp-bundles" / "demo-bundle"
    assert installed.is_dir()
    assert main(["--json", "mcp", "remove", "demo-bundle"]) == 0
    _json(capsys)
    assert not installed.exists()


def test_registry_metadata_resolution() -> None:
    remote = registry_install_config(
        {"server": {"name": "remote", "remotes": [{"url": "https://x.test/mcp"}]}}
    )
    package = registry_install_config(
        {
            "server": {
                "name": "package",
                "packages": [{"registryType": "npm", "identifier": "@example/mcp"}],
            }
        }
    )
    assert remote.url == "https://x.test/mcp"
    assert package.command == "npx"


def test_registry_search_and_add_commands(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRegistry:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        async def search(self, query: str, *, limit: int = 20) -> tuple[dict[str, Any], ...]:
            return ({"server": {"name": query}, "limit": limit},)

        async def get(self, name: str, version: str = "latest") -> dict[str, Any]:
            return {
                "server": {
                    "name": name,
                    "remotes": [{"url": "https://registry.test/mcp"}],
                }
            }

    monkeypatch.setattr(cli_module, "OfficialMCPRegistry", FakeRegistry)
    assert main(["--json", "mcp", "search", "demo", "--limit", "3"]) == 0
    assert _json(capsys)[0]["limit"] == 3
    assert main(["--json", "mcp", "add", "registry-demo", "--registry"]) == 0
    assert _json(capsys)["url"] == "https://registry.test/mcp"


def test_mcp_store_rejects_duplicate_import(project: Path) -> None:
    paths = CLIPaths.resolve(project)
    paths.ensure()
    store = MCPConfigStore(paths.mcp_config)
    config = project / "mcp.json"
    config.write_text(
        json.dumps({"mcpServers": {"one": {"command": "python"}}}),
        encoding="utf-8",
    )
    store.import_file(config)
    with pytest.raises(Exception, match="configured names"):
        store.import_file(config)


def test_plugin_full_lifecycle(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = _plugin(project / "sources")
    assert main(["--json", "plugin", "add", str(source)]) == 0
    assert _json(capsys)["name"] == "demo-plugin"
    assert main(["--json", "plugin", "list"]) == 0
    assert _json(capsys)[0]["version"] == "1.0.0"
    manifest = source / ".super-harness" / "plugin.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace('version = "1.0.0"', 'version = "1.1.0"'),
        encoding="utf-8",
    )
    assert main(["--json", "plugin", "update", "demo-plugin"]) == 0
    assert _json(capsys)["version"] == "1.1.0"
    assert main(["--json", "plugin", "info", "demo-plugin"]) == 0
    assert _json(capsys)["enabled"] is False
    assert main(["--json", "plugin", "remove", "demo-plugin"]) == 0
    assert _json(capsys)["removed"] == "demo-plugin"


def test_thread_inspect_omits_content_by_default(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = CLIPaths.resolve(project)
    paths.ensure()
    with SQLiteThreadStore(paths.threads) as store:
        thread = Agent(EchoProvider(), store=store).thread()
        thread.run("api_key=sk-abcdefghijklmnop")
        thread_id = thread.thread_id
    assert main(["--json", "thread", "inspect", thread_id]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["message_count"] == 2
    assert "messages" not in result
    assert "sk-abcdefghijklmnop" not in output


def test_provider_test_uses_provider_boundary(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = EchoProvider()

    def fake_provider(args: argparse.Namespace) -> EchoProvider:
        return provider

    monkeypatch.setattr(cli_module, "_make_provider", fake_provider)
    assert main(["--json", "provider", "test", "--prompt", "ping"]) == 0
    result = _json(capsys)
    assert result == {
        "ok": True,
        "provider": "echo",
        "model": "echo-1",
        "response": "ok",
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }


def test_thread_resume_uses_persisted_history(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = CLIPaths.resolve(project)
    paths.ensure()
    with SQLiteThreadStore(paths.threads) as store:
        thread = Agent(EchoProvider(), store=store).thread()
        thread.run("first")
        thread_id = thread.thread_id
    provider = EchoProvider()

    def fake_provider(args: argparse.Namespace) -> EchoProvider:
        return provider

    monkeypatch.setattr(cli_module, "_make_provider", fake_provider)
    assert main(["--json", "thread", "resume", thread_id, "second"]) == 0
    result = _json(capsys)
    assert result["thread_id"] == thread_id
    assert result["response"] == "ok"
    with SQLiteThreadStore(paths.threads) as store:
        assert len(store.load(thread_id).turns) == 2


def test_failures_have_nonzero_exit_and_safe_json(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--json", "skill", "info", "missing"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["ok"] is False
    assert "missing" in error["error"]["message"]
