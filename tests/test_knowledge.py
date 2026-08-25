from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, cast

import httpx
import pytest

from super_harness import (
    Agent,
    HTTPRAGProvider,
    KnowledgeRouter,
    KnowledgeTrace,
    ZhipuVisionProvider,
    ZhipuWebSearchProvider,
)
from super_harness.context import ContextKind
from super_harness.exceptions import RAGError, SearchError, VisionError
from super_harness.models import (
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelStreamEventType,
)
from tests.services.rag_server import RAGHandler


class KnowledgeHandler(BaseHTTPRequestHandler):
    requests: ClassVar[list[dict[str, Any]]] = []
    headers_seen: ClassVar[list[dict[str, str]]] = []

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        decoded: object = json.loads(self.rfile.read(length))
        assert isinstance(decoded, dict)
        self.requests.append(cast(dict[str, Any], decoded))
        self.headers_seen.append(dict(self.headers))
        if self.path == "/search":
            value = {
                "search_result": [
                    {
                        "title": "Fresh result",
                        "link": "https://example.test/fresh",
                        "content": "Current evidence",
                        "publish_date": "2026-08-25",
                    }
                ]
            }
        elif self.path == "/vision":
            value = {"choices": [{"message": {"content": "a red pixel"}}]}
        else:
            self.send_error(404)
            return
        payload = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        return


class EvidenceModel:
    name = "evidence-model"
    capabilities = ModelCapabilities(tools=False, structured_output=False)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        context = "\n".join(message.content for message in request.messages)
        answer = "canary deployment" if "canary deployment" in context else "missing evidence"
        return ModelResponse(answer)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent(ModelStreamEventType.STARTED)
        response = await self.complete(request)
        yield ModelStreamEvent(ModelStreamEventType.TEXT_DELTA, delta=response.text)
        yield ModelStreamEvent(ModelStreamEventType.COMPLETED, response=response)

    async def aclose(self) -> None:
        return


def _server(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = cast(tuple[str, int], server.server_address)
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def knowledge_server() -> Iterator[str]:
    KnowledgeHandler.requests = []
    KnowledgeHandler.headers_seen = []
    yield from _server(KnowledgeHandler)


@pytest.fixture
def rag_server() -> Iterator[str]:
    RAGHandler.requests = []
    RAGHandler.token = "rag-test-token"
    yield from _server(RAGHandler)
    RAGHandler.token = None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_and_vision_use_real_local_http(knowledge_server: str, tmp_path: Path) -> None:
    traces: list[KnowledgeTrace] = []
    search = ZhipuWebSearchProvider(
        api_key="local-search-token",
        endpoint=f"{knowledge_server}/search",
        trace_sink=traces.append,
    )
    image = tmp_path / "pixel.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nlocal-fixture")
    vision = ZhipuVisionProvider(
        api_key="local-vision-token",
        endpoint=f"{knowledge_server}/vision",
        trace_sink=traces.append,
    )

    found = await search.search("fresh evidence", top_n=1)
    seen = await vision.analyze(image, "Describe this image")

    assert found.results[0].url == "https://example.test/fresh"
    assert seen.text == "a red pixel"
    assert [trace.operation for trace in traces] == ["search", "vision"]
    assert KnowledgeHandler.requests[0]["count"] == 1
    content = cast(
        list[dict[str, Any]],
        cast(list[dict[str, Any]], KnowledgeHandler.requests[1]["messages"])[0]["content"],
    )
    assert str(cast(dict[str, Any], content[0]["image_url"])["url"]).startswith(
        "data:image/png;base64,"
    )
    assert all("local-" not in json.dumps(request) for request in KnowledgeHandler.requests)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rag_fixture_normalization_context_tools_and_auth(rag_server: str) -> None:
    traces: list[KnowledgeTrace] = []
    provider = HTTPRAGProvider(rag_server, api_key="rag-test-token", trace_sink=traces.append)
    router = KnowledgeRouter(rag=provider)

    documents = await provider.retrieve("release policy production", top_n=1)
    fragments = await router.rag_context("release policy production", top_n=1)
    rag_tool = router.tools()[0]
    output = await rag_tool.invoke({"query": "release policy", "top_n": 1})
    answer = await Agent(EvidenceModel(), context=fragments).arun("What is the release policy?")

    assert len(documents) == 1
    assert "canary deployment" in documents[0].text
    assert fragments[0].kind is ContextKind.RAG
    assert fragments[0].role.value == "user"
    assert "canary deployment" in str(output)
    assert "canary deployment" in answer.text
    assert RAGHandler.requests[0] == {"query": "release policy production", "top_n": 1}
    assert all(trace.operation == "retrieve" for trace in traces)


@pytest.mark.asyncio
async def test_simple_rag_response_and_typed_malformed_error() -> None:
    async def simple(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": ["A", "B"]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(simple))
    provider = HTTPRAGProvider("https://rag.test", client=client)
    try:
        result = await provider.retrieve("query", top_n=1)
    finally:
        await client.aclose()
    assert [item.text for item in result] == ["A"]

    async def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"wrong": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(malformed))
    provider = HTTPRAGProvider("https://rag.test", client=client)
    try:
        with pytest.raises(RAGError, match="results list"):
            await provider.retrieve("query")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_provider_errors_timeout_retry_and_cancellation() -> None:
    attempts = 0

    async def transient(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(transient))
    provider = ZhipuWebSearchProvider(api_key="test", client=client, retries=1)
    try:
        with pytest.raises(SearchError):
            await provider.search("query")
    finally:
        await client.aclose()
    assert attempts == 2

    async def blocking(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(blocking))
    vision = ZhipuVisionProvider(api_key="test", client=client)
    task = asyncio.create_task(vision.analyze("https://example.test/image.png", "look"))
    await asyncio.sleep(0)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await client.aclose()

    with pytest.raises(VisionError, match="required"):
        await ZhipuVisionProvider(api_key="").analyze("https://example.test/a.png", "look")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rag_real_http_timeout_and_typed_error(rag_server: str) -> None:
    provider = HTTPRAGProvider(
        rag_server,
        api_key="rag-test-token",
        retrieve_path="/test/slow",
        timeout=0.03,
        retries=0,
    )
    with pytest.raises(RAGError) as caught:
        await provider.retrieve("release")
    assert caught.value.details["status_code"] is None
    assert "rag-test-token" not in str(caught.value.details)

    malformed = HTTPRAGProvider(
        rag_server,
        api_key="rag-test-token",
        retrieve_path="/test/malformed",
        retries=0,
    )
    with pytest.raises(RAGError, match="results list"):
        await malformed.retrieve("release")

    failing = HTTPRAGProvider(
        rag_server,
        api_key="rag-test-token",
        retrieve_path="/test/error",
        retries=0,
    )
    with pytest.raises(RAGError) as server_error:
        await failing.retrieve("release")
    assert server_error.value.details["status_code"] == 500
