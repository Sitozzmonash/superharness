"""Replaceable Official MCP Registry preview adapter."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx

from super_harness.exceptions import MCPError


class MCPRegistry(Protocol):
    async def search(self, query: str, *, limit: int = 20) -> tuple[Mapping[str, Any], ...]: ...

    async def get(self, name: str, version: str = "latest") -> Mapping[str, Any]: ...


class OfficialMCPRegistry:
    def __init__(
        self,
        base_url: str = "https://registry.modelcontextprotocol.io",
        *,
        timeout: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client

    async def search(self, query: str, *, limit: int = 20) -> tuple[Mapping[str, Any], ...]:
        if not query.strip() or not 1 <= limit <= 100:
            raise ValueError("registry query must be non-empty and limit between 1 and 100")
        payload = await self._get("/v0.1/servers", params={"search": query, "limit": limit})
        servers = payload.get("servers")
        if not isinstance(servers, list):
            raise MCPError("registry response has invalid servers")
        return tuple(
            cast(Mapping[str, Any], item)
            for item in cast(list[Any], servers)
            if isinstance(item, dict)
        )

    async def get(self, name: str, version: str = "latest") -> Mapping[str, Any]:
        encoded_name = quote(name, safe="")
        encoded_version = quote(version, safe="")
        return await self._get(f"/v0.1/servers/{encoded_name}/versions/{encoded_version}")

    async def _get(
        self, path: str, *, params: Mapping[str, str | int] | None = None
    ) -> Mapping[str, Any]:
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("registry response must be an object")
            return cast(Mapping[str, Any], payload)
        except (httpx.HTTPError, ValueError) as exc:
            raise MCPError("MCP registry request failed", details={"path": path}) from exc
        finally:
            if owned:
                await client.aclose()
