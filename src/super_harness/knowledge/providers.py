"""Async provider contracts and HTTP adapters for external knowledge."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

from super_harness.exceptions import RAGError, SearchError, VisionError

from .types import KnowledgeTrace, RAGDocument, SearchResponse, SearchResult, VisionResult

TraceSink = Callable[[KnowledgeTrace], Awaitable[None] | None]


class WebSearchProvider(Protocol):
    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse: ...


class RAGProvider(Protocol):
    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]: ...


class VisionProvider(Protocol):
    async def analyze(self, image: str | Path, prompt: str) -> VisionResult: ...


async def _emit(sink: TraceSink | None, event: KnowledgeTrace) -> None:
    if sink is None:
        return
    result = sink(event)
    if isinstance(result, Awaitable):
        await result


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: Mapping[str, Any],
    headers: Mapping[str, str],
    retries: int,
    error_type: type[RAGError] | type[SearchError] | type[VisionError],
) -> Mapping[str, Any]:
    for attempt in range(retries + 1):
        try:
            response = await client.post(url, json=dict(json), headers=dict(headers))
            if response.status_code in {408, 429, 500, 502, 503, 504} and attempt < retries:
                await asyncio.sleep(0.05 * (2**attempt))
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("response must be a JSON object")
            return cast(Mapping[str, Any], payload)
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            if isinstance(exc, httpx.TransportError) and attempt < retries:
                await asyncio.sleep(0.05 * (2**attempt))
                continue
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            raise error_type(
                "external provider request failed",
                details={"endpoint": url, "status_code": status, "attempt": attempt + 1},
            ) from exc
    raise AssertionError("retry loop exhausted")


class ZhipuWebSearchProvider:
    """Zhipu standalone web-search adapter."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = "https://open.bigmodel.cn/api/paas/v4/web_search",
        timeout: float = 20.0,
        retries: int = 2,
        client: httpx.AsyncClient | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ZHIPU_SEARCH_API_KEY")
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries
        self._client = client
        self.trace_sink = trace_sink

    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse:
        if not query.strip() or top_n < 1:
            raise ValueError("query must be non-empty and top_n must be positive")
        if not self._api_key:
            raise SearchError("ZHIPU_SEARCH_API_KEY is required")
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            payload = await _post_with_retry(
                client,
                self.endpoint,
                json={"search_query": query, "search_engine": "search_std", "count": top_n},
                headers={"Authorization": f"Bearer {self._api_key}"},
                retries=self.retries,
                error_type=SearchError,
            )
            raw_results = payload.get("search_result", payload.get("results", []))
            if not isinstance(raw_results, list):
                raise SearchError("web-search response has invalid results")
            results: list[SearchResult] = []
            for raw_value in cast(list[Any], raw_results)[:top_n]:
                raw = raw_value
                if not isinstance(raw, dict):
                    continue
                item = cast(Mapping[str, Any], raw)
                results.append(
                    SearchResult(
                        title=str(item.get("title", "")),
                        url=str(item.get("link", item.get("url", ""))),
                        snippet=str(item.get("content", item.get("snippet", ""))),
                        published_at=(
                            str(item["publish_date"]) if item.get("publish_date") else None
                        ),
                        metadata={"refer": item.get("refer")},
                    )
                )
            response = SearchResponse(query, tuple(results), "zhipu")
            await _emit(self.trace_sink, KnowledgeTrace("search", "zhipu", True, len(results)))
            return response
        except SearchError:
            await _emit(self.trace_sink, KnowledgeTrace("search", "zhipu", False))
            raise
        finally:
            if owned:
                await client.aclose()


class HTTPRAGProvider:
    """Adapter for the frozen POST /retrieve RAG contract."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        api_key: str | None = None,
        retrieve_path: str = "/retrieve",
        timeout: float = 10.0,
        retries: int = 1,
        client: httpx.AsyncClient | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("RAG_BASE_URL", "")).rstrip("/")
        self._api_key = api_key or os.environ.get("RAG_API_KEY")
        self.retrieve_path = "/" + retrieve_path.lstrip("/")
        self.timeout = timeout
        self.retries = retries
        self._client = client
        self.trace_sink = trace_sink

    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]:
        if not self.base_url:
            raise RAGError("RAG_BASE_URL is required")
        if not query.strip() or top_n < 1:
            raise ValueError("query must be non-empty and top_n must be positive")
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            payload = await _post_with_retry(
                client,
                f"{self.base_url}{self.retrieve_path}",
                json={"query": query, "top_n": top_n},
                headers=headers,
                retries=self.retries,
                error_type=RAGError,
            )
            raw_results = payload.get("results")
            if not isinstance(raw_results, list):
                raise RAGError("RAG response must contain a results list")
            documents: list[RAGDocument] = []
            for raw_value in cast(list[Any], raw_results)[:top_n]:
                raw = raw_value
                if isinstance(raw, str):
                    documents.append(RAGDocument(raw))
                elif isinstance(raw, dict):
                    item = cast(Mapping[str, Any], raw)
                    text = item.get("text")
                    if not isinstance(text, str):
                        raise RAGError("RAG result item has invalid shape")
                    metadata = item.get("metadata", {})
                    documents.append(
                        RAGDocument(
                            text,
                            float(item["score"]) if item.get("score") is not None else None,
                            str(item["source"]) if item.get("source") is not None else None,
                            cast(Mapping[str, Any], metadata) if isinstance(metadata, dict) else {},
                        )
                    )
                else:
                    raise RAGError("RAG result item has invalid shape")
            result = tuple(documents)
            await _emit(self.trace_sink, KnowledgeTrace("retrieve", "http-rag", True, len(result)))
            return result
        except RAGError:
            await _emit(self.trace_sink, KnowledgeTrace("retrieve", "http-rag", False))
            raise
        finally:
            if owned:
                await client.aclose()


class ZhipuVisionProvider:
    """GLM-4V adapter supporting local files, data URLs, and HTTPS image URLs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model: str = "glm-4v-flash",
        timeout: float = 30.0,
        retries: int = 1,
        max_image_bytes: int = 10_000_000,
        client: httpx.AsyncClient | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ZHIPU_VISION_API_KEY")
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.max_image_bytes = max_image_bytes
        self._client = client
        self.trace_sink = trace_sink

    async def analyze(self, image: str | Path, prompt: str) -> VisionResult:
        if not self._api_key:
            raise VisionError("ZHIPU_VISION_API_KEY is required")
        if not prompt.strip():
            raise ValueError("vision prompt must be non-empty")
        image_url = await self._image_url(image)
        owned = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            payload = await _post_with_retry(
                client,
                self.endpoint,
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": image_url}},
                                {"type": "text", "text": prompt},
                            ],
                        }
                    ],
                },
                headers={"Authorization": f"Bearer {self._api_key}"},
                retries=self.retries,
                error_type=VisionError,
            )
            try:
                choices = cast(list[Any], payload["choices"])
                message = cast(Mapping[str, Any], cast(Mapping[str, Any], choices[0])["message"])
                text = str(message["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise VisionError("vision response has invalid choices") from exc
            await _emit(
                self.trace_sink, KnowledgeTrace("vision", "zhipu", True, 1, {"model": self.model})
            )
            return VisionResult(text, self.model, "zhipu")
        except VisionError:
            await _emit(
                self.trace_sink,
                KnowledgeTrace("vision", "zhipu", False, metadata={"model": self.model}),
            )
            raise
        finally:
            if owned:
                await client.aclose()

    async def _image_url(self, image: str | Path) -> str:
        value = str(image)
        if value.startswith(("https://", "http://", "data:")):
            return value
        path = Path(image)
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except OSError as exc:
            raise VisionError("unable to read local image", details={"path": str(path)}) from exc
        if len(data) > self.max_image_bytes:
            raise VisionError("local image exceeds size limit", details={"bytes": len(data)})
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        signatures = {
            "image/png": (b"\x89PNG\r\n\x1a\n",),
            "image/jpeg": (b"\xff\xd8\xff",),
            "image/gif": (b"GIF87a", b"GIF89a"),
            "image/webp": (b"RIFF",),
        }
        valid_signatures = signatures.get(mime)
        valid = valid_signatures is not None and any(
            data.startswith(item) for item in valid_signatures
        )
        if not valid or (mime == "image/webp" and data[8:12] != b"WEBP"):
            raise VisionError("local input is not a recognized image", details={"path": str(path)})
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"
