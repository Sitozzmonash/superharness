from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from super_harness import (
    MCPClient,
    MCPServerConfig,
    MCPTransport,
    Observability,
    OfficialMCPRegistry,
    StructuredLogger,
    import_mcp_servers,
    inspect_mcpb,
    install_mcpb,
)
from super_harness.exceptions import MCPError


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return cast(tuple[str, int], candidate.getsockname())[1]


@pytest.fixture
def mcp_script() -> Path:
    return Path(__file__).parent / "services" / "mcp_server.py"


@pytest.fixture
def mcp_http_server(mcp_script: Path) -> Iterator[str]:
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, str(mcp_script), "streamable-http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            if process.poll() is not None:
                raise RuntimeError("MCP HTTP fixture exited during startup") from None
            time.sleep(0.05)
    else:
        process.terminate()
        raise RuntimeError("MCP HTTP fixture did not start")
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_stdio_mcp_tools_resources_prompts_and_adapter(mcp_script: Path) -> None:
    telemetry = io.StringIO()
    observer = Observability(logger=StructuredLogger(console=None, jsonl=telemetry))
    config = MCPServerConfig(
        "local",
        MCPTransport.STDIO,
        command=sys.executable,
        args=(str(mcp_script), "stdio"),
        include_tools=("add",),
        timeout=10,
    )
    async with MCPClient(config, observer=observer) as client:
        tools = await client.list_tools()
        result = await client.call_tool("add", {"left": 20, "right": 22})
        resources = await client.list_resources()
        resource = await client.read_resource("note://release")
        prompts = await client.list_prompts()
        prompt = await client.get_prompt("summarize", {"topic": "MCP"})
        adapted = await client.as_tools()
        adapted_result = await adapted[0].invoke({"left": 1, "right": 2})

    assert {cast(Any, item).name for item in tools} == {"add", "slow"}
    assert result["structuredContent"] == {"result": 42}
    assert cast(Any, resources[0]).uri == "note://release"
    assert "canary" in json.dumps(resource)
    assert cast(Any, prompts[0]).name == "summarize"
    assert "Summarize MCP" in json.dumps(prompt)
    assert adapted[0].qualified_name == "local.add"
    observed = {json.loads(line)["event"] for line in telemetry.getvalue().splitlines()}
    assert observed >= {"mcp.connected", "mcp.call.started", "mcp.call.completed"}
    assert cast(dict[str, Any], adapted_result)["structuredContent"] == {"result": 3}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_streamable_http_uses_2026_protocol_and_filter(
    mcp_http_server: str,
) -> None:
    config = MCPServerConfig(
        "http",
        MCPTransport.STREAMABLE_HTTP,
        url=mcp_http_server,
        exclude_tools=("slow",),
        timeout=10,
    )
    async with MCPClient(config) as client:
        assert client.protocol_version == "2026-07-28"
        tools = await client.as_tools()
        result = await client.call_tool("add", {"left": 2, "right": 3})
        with pytest.raises(MCPError, match="disabled"):
            await client.call_tool("slow", {"delay": 0.01})
    assert [item.qualified_name for item in tools] == ["http.add"]
    assert result["structuredContent"] == {"result": 5}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_timeout_is_typed_and_cancellation_propagates(mcp_script: Path) -> None:
    timeout_config = MCPServerConfig(
        "timeout",
        MCPTransport.STDIO,
        command=sys.executable,
        args=(str(mcp_script), "stdio"),
        timeout=0.05,
    )
    async with MCPClient(timeout_config) as client:
        with pytest.raises(MCPError, match="timed out"):
            await client.call_tool("slow", {"delay": 1.0})

    cancel_config = MCPServerConfig(
        "cancel",
        MCPTransport.STDIO,
        command=sys.executable,
        args=(str(mcp_script), "stdio"),
        timeout=10,
    )
    async with MCPClient(cancel_config) as client:
        task = asyncio.create_task(client.call_tool("slow", {"delay": 1.0}))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_import_common_mcp_servers_config() -> None:
    configs = import_mcp_servers(
        {
            "mcpServers": {
                "files": {"command": "python", "args": ["server.py"], "env": {"MODE": "test"}},
                "remote": {
                    "url": "https://example.test/mcp",
                    "headers": {"X-Test": "yes"},
                    "timeout": 12,
                    "excludeTools": ["danger"],
                },
            }
        }
    )
    assert configs[0].transport is MCPTransport.STDIO
    assert configs[0].args == ("server.py",)
    assert configs[1].transport is MCPTransport.STREAMABLE_HTTP
    assert configs[1].headers["X-Test"] == "yes"
    assert configs[1].timeout == 12
    assert configs[1].exclude_tools == ("danger",)


def test_mcpb_integrity_safe_install_and_traversal_rejection(tmp_path: Path) -> None:
    bundle_path = tmp_path / "demo.mcpb"
    manifest = {
        "manifest_version": "0.3",
        "name": "demo",
        "version": "1.0.0",
        "description": "Demo bundle",
        "author": {"name": "Tester"},
        "server": {
            "type": "python",
            "entry_point": "server.py",
            "mcp_config": {"command": "python", "args": ["${__dirname}/server.py"]},
        },
    }
    with zipfile.ZipFile(bundle_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("server.py", "print('server')")
    digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()

    inspected = inspect_mcpb(bundle_path, expected_sha256=digest)
    installed = install_mcpb(bundle_path, tmp_path / "installed", expected_sha256=digest)
    assert inspected.name == installed.name == "demo"
    assert (tmp_path / "installed" / "demo" / "server.py").is_file()
    assert "${__dirname}" not in installed.config.args[0]
    assert Path(installed.config.args[0]).is_absolute()
    with pytest.raises(MCPError, match="integrity"):
        inspect_mcpb(bundle_path, expected_sha256="0" * 64)

    unsafe = tmp_path / "unsafe.mcpb"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("../escape.py", "bad")
    with pytest.raises(MCPError, match="unsafe"):
        inspect_mcpb(unsafe)


@pytest.mark.asyncio
async def test_replaceable_registry_adapter_normalizes_preview_api() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/servers"):
            return httpx.Response(200, json={"servers": [{"server": {"name": "demo"}}]})
        return httpx.Response(200, json={"server": {"name": "demo", "version": "1.0.0"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    registry = OfficialMCPRegistry("https://registry.test", client=http)
    try:
        found = await registry.search("demo", limit=1)
        detail = await registry.get("io.example/demo")
    finally:
        await http.aclose()
    assert cast(dict[str, Any], found[0])["server"] == {"name": "demo"}
    assert detail["server"] == {"name": "demo", "version": "1.0.0"}


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_official_mcp_1x_2025_protocol_compatibility() -> None:
    if os.environ.get("SUPER_HARNESS_EXTERNAL_COMPAT") != "1":
        pytest.skip("set SUPER_HARNESS_EXTERNAL_COMPAT=1 for MCP 1.x compatibility E2E")
    script = Path(__file__).parent / "services" / "mcp_2025_server.py"
    config = MCPServerConfig(
        "mcp-2025",
        MCPTransport.STDIO,
        command="uv",
        args=("run", "--isolated", "--with", "mcp==1.29.1", "python", str(script)),
        timeout=30,
    )
    async with MCPClient(config) as client:
        assert client.protocol_version in {"2025-03-26", "2025-06-18", "2025-11-25"}
        result = await client.call_tool("legacy_add", {"left": 20, "right": 22})
    assert result["structuredContent"] == {"result": 42}


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_real_official_registry_search() -> None:
    if os.environ.get("SUPER_HARNESS_EXTERNAL_COMPAT") != "1":
        pytest.skip("set SUPER_HARNESS_EXTERNAL_COMPAT=1 for Registry E2E")
    found = await OfficialMCPRegistry().search("filesystem", limit=3)
    assert found
