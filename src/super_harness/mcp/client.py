"""Official MCP SDK adapter for stdio and Streamable HTTP."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable
from contextlib import AsyncExitStack
from typing import Any, TypeVar, cast
from uuid import uuid4

import httpx2
from mcp import StdioServerParameters
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError as MCP_SDK_ERROR
from pydantic import BaseModel, ConfigDict, create_model

from super_harness.exceptions import MCPError
from super_harness.runtime.events import Event, EventObserver
from super_harness.tools import Tool, ToolMetadata

from .config import MCPServerConfig, MCPTransport


def _is_sdk_timeout(exc: MCP_SDK_ERROR) -> bool:
    """Detect SDK read-timeout errors that should surface as ``timed out``."""
    msg = str(exc).casefold()
    return "timed out" in msg or "read timeout" in msg


T = TypeVar("T")
_MAX_PAGES = 20
_MAX_ITEMS = 1_000


class MCPClient:
    def __init__(
        self,
        config: MCPServerConfig,
        *,
        observer: EventObserver | None = None,
    ) -> None:
        self.config = config
        self.observer = observer
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None

    async def __aenter__(self) -> MCPClient:
        if not self.config.enabled:
            raise MCPError(f"MCP server {self.config.name!r} is disabled")
        stack = AsyncExitStack()
        try:
            if self.config.transport is MCPTransport.STDIO:
                target: object = StdioServerParameters(
                    command=cast(str, self.config.command),
                    args=list(self.config.args),
                    env=dict(self.config.env) or None,
                    cwd=self.config.cwd,
                )
            else:
                http = await stack.enter_async_context(
                    httpx2.AsyncClient(
                        headers=dict(self.config.headers),
                        timeout=httpx2.Timeout(self.config.timeout, read=self.config.timeout),
                        follow_redirects=False,
                    )
                )
                target = streamable_http_client(cast(str, self.config.url), http_client=http)
            client = Client(cast(Any, target), read_timeout_seconds=self.config.timeout)
            # Enter the SDK context directly (no asyncio.wait_for wrapper): wrapping
            # its anyio-based async context manager in a separate asyncio task corrupts
            # anyio's cancel scope on Python 3.11.
            self._client = await stack.enter_async_context(client)
            self._stack = stack
            await self._observe(
                Event(
                    "mcp.connected",
                    payload={
                        "server": self.config.name,
                        "transport": self.config.transport.value,
                        "protocol_version": client.protocol_version,
                    },
                )
            )
            return self
        except asyncio.CancelledError:
            await stack.aclose()
            raise
        except Exception as exc:
            await stack.aclose()
            if isinstance(exc, MCPError):
                raise
            raise MCPError(f"MCP server {self.config.name!r} connection failed") from exc

    async def __aexit__(self, *exc: object) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._client = None

    @property
    def protocol_version(self) -> str | None:
        client = self._require()
        return client.protocol_version

    @property
    def capabilities(self) -> object:
        return self._require().server_capabilities

    async def list_tools(self) -> tuple[object, ...]:
        items: list[object] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            result = await self._run(self._require().list_tools(cursor=cursor), "list tools")
            items.extend(result.tools)
            cursor = _next_cursor(result.next_cursor, seen)
            if cursor is None:
                return tuple(items)
            if len(items) > _MAX_ITEMS:
                raise MCPError("MCP tool catalog exceeds item limit")
        raise MCPError("MCP tool catalog exceeds pagination limit")

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._allow_tool(name)
        result = await self._run(self._require().call_tool(name, arguments or {}), "call tool")
        return result.model_dump(mode="json", by_alias=True)

    async def list_resources(self) -> tuple[object, ...]:
        items: list[object] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            result = await self._run(
                self._require().list_resources(cursor=cursor), "list resources"
            )
            items.extend(result.resources)
            cursor = _next_cursor(result.next_cursor, seen)
            if cursor is None:
                return tuple(items)
            if len(items) > _MAX_ITEMS:
                raise MCPError("MCP resource catalog exceeds item limit")
        raise MCPError("MCP resource catalog exceeds pagination limit")

    async def read_resource(self, uri: str) -> dict[str, Any]:
        result = await self._run(self._require().read_resource(uri), "read resource")
        return result.model_dump(mode="json", by_alias=True)

    async def list_prompts(self) -> tuple[object, ...]:
        items: list[object] = []
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(_MAX_PAGES):
            result = await self._run(self._require().list_prompts(cursor=cursor), "list prompts")
            items.extend(result.prompts)
            cursor = _next_cursor(result.next_cursor, seen)
            if cursor is None:
                return tuple(items)
            if len(items) > _MAX_ITEMS:
                raise MCPError("MCP prompt catalog exceeds item limit")
        raise MCPError("MCP prompt catalog exceeds pagination limit")

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None
    ) -> dict[str, Any]:
        result = await self._run(self._require().get_prompt(name, arguments or {}), "get prompt")
        return result.model_dump(mode="json", by_alias=True)

    async def as_tools(self) -> tuple[Tool, ...]:
        tools: list[Tool] = []
        for raw in await self.list_tools():
            item = cast(Any, raw)
            name = str(item.name)
            if not self._tool_allowed(name):
                continue
            schema = item.input_schema
            model = _arguments_model(name, schema)

            async def invoke(_name: str = name, **arguments: Any) -> dict[str, Any]:
                return await self.call_tool(_name, arguments)

            tools.append(
                Tool(
                    name,
                    str(item.description or name),
                    model,
                    invoke,
                    ToolMetadata(
                        namespace=self.config.name,
                        source="mcp",
                        risk="external",
                        timeout=self.config.timeout,
                    ),
                )
            )
        return tuple(tools)

    def _require(self) -> Client:
        if self._client is None:
            raise MCPError("MCP client must be used as an async context manager")
        return self._client

    def _tool_allowed(self, name: str) -> bool:
        return (
            not self.config.include_tools or name in self.config.include_tools
        ) and name not in self.config.exclude_tools

    def _allow_tool(self, name: str) -> None:
        if not self._tool_allowed(name):
            raise MCPError(f"MCP tool {name!r} is disabled by filter")

    async def _run(self, operation: Awaitable[T], label: str) -> T:
        started = time.monotonic()
        operation_id = uuid4().hex
        await self._observe(
            Event(
                "mcp.call.started",
                payload={
                    "server": self.config.name,
                    "operation": label,
                    "operation_id": operation_id,
                },
            )
        )
        try:
            # The SDK Client is created with read_timeout_seconds=self.config.timeout,
            # so it enforces the operation timeout itself. We must NOT re-wrap the
            # operation in asyncio.wait_for: on Python 3.11 that wraps an anyio-based
            # SDK coroutine in a separate asyncio task, and cancelling/awaiting it
            # corrupts anyio's cancel scope ("exit cancel scope in a different task").
            # The SDK timeout surfaces as an mcp.shared.exceptions.MCPError, which we
            # normalize below into a typed "timed out" MCPError.
            result = await operation
            await self._observe(
                Event(
                    "mcp.call.completed",
                    payload={
                        "server": self.config.name,
                        "operation": label,
                        "operation_id": operation_id,
                        "duration_ms": (time.monotonic() - started) * 1000,
                    },
                )
            )
            return result
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            await self._failed(label, operation_id, started, exc)
            raise MCPError(f"MCP {label} timed out") from exc
        except MCP_SDK_ERROR as exc:
            await self._failed(label, operation_id, started, exc)
            if _is_sdk_timeout(exc):
                raise MCPError(f"MCP {label} timed out") from exc
            raise MCPError(f"MCP {label} failed") from exc
        except Exception as exc:
            await self._failed(label, operation_id, started, exc)
            raise MCPError(f"MCP {label} failed") from exc

    async def _failed(
        self,
        label: str,
        operation_id: str,
        started: float,
        error: Exception,
    ) -> None:
        await self._observe(
            Event(
                "mcp.call.failed",
                payload={
                    "server": self.config.name,
                    "operation": label,
                    "operation_id": operation_id,
                    "duration_ms": (time.monotonic() - started) * 1000,
                    "error_class": type(error).__name__,
                },
            )
        )

    async def _observe(self, event: Event) -> None:
        if self.observer is None:
            return
        outcome = self.observer.observe(event)
        if inspect.isawaitable(outcome):
            await cast(Awaitable[object], outcome)


def _arguments_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, tuple[Any, Any]] = {}
    if isinstance(properties, dict):
        for key in cast(dict[str, Any], properties):
            fields[str(key)] = (Any, ... if key in required else None)
    factory = cast(Any, create_model)
    return cast(
        type[BaseModel],
        factory(
            f"MCP{name.title().replace('_', '')}Arguments",
            __config__=ConfigDict(extra="forbid"),
            **fields,
        ),
    )


def _next_cursor(cursor: str | None, seen: set[str]) -> str | None:
    if cursor is None:
        return None
    if len(cursor.encode()) > 4_096:
        raise MCPError("MCP pagination cursor exceeds size limit")
    if cursor in seen:
        raise MCPError("MCP returned a repeated pagination cursor")
    seen.add(cursor)
    return cursor
