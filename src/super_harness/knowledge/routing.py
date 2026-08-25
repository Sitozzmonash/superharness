"""Routing, context injection, and model-visible knowledge tools."""

from __future__ import annotations

from super_harness.context import ContextFragment, ContextKind
from super_harness.tools import Tool, tool

from .providers import RAGProvider, VisionProvider, WebSearchProvider
from .types import RAGDocument, SearchResponse, VisionResult


class KnowledgeRouter:
    def __init__(
        self,
        *,
        search: WebSearchProvider | None = None,
        rag: RAGProvider | None = None,
        vision: VisionProvider | None = None,
    ) -> None:
        self.search_provider = search
        self.rag_provider = rag
        self.vision_provider = vision

    async def search(self, query: str, *, top_n: int = 5) -> SearchResponse:
        if self.search_provider is None:
            raise RuntimeError("web search provider is not configured")
        return await self.search_provider.search(query, top_n=top_n)

    async def retrieve(self, query: str, *, top_n: int = 3) -> tuple[RAGDocument, ...]:
        if self.rag_provider is None:
            raise RuntimeError("RAG provider is not configured")
        return await self.rag_provider.retrieve(query, top_n=top_n)

    async def vision(self, image: str, prompt: str) -> VisionResult:
        if self.vision_provider is None:
            raise RuntimeError("vision provider is not configured")
        return await self.vision_provider.analyze(image, prompt)

    async def rag_context(self, query: str, *, top_n: int = 3) -> tuple[ContextFragment, ...]:
        documents = await self.retrieve(query, top_n=top_n)
        return tuple(
            ContextFragment(
                ContextKind.RAG,
                document.text,
                document.source or f"rag:{index}",
                metadata={"score": document.score, **document.metadata},
            )
            for index, document in enumerate(documents, start=1)
        )

    async def search_context(self, query: str, *, top_n: int = 5) -> tuple[ContextFragment, ...]:
        response = await self.search(query, top_n=top_n)
        return tuple(
            ContextFragment(
                ContextKind.RAG,
                f"{item.title}\n{item.snippet}\nURL: {item.url}",
                item.url or f"search:{index}",
                metadata={"provider": response.provider, "query": response.query},
            )
            for index, item in enumerate(response.results, start=1)
        )

    def tools(self) -> tuple[Tool, ...]:
        items: list[Tool] = []
        if self.search_provider is not None:

            @tool(
                name="web_search", namespace="knowledge", source="provider", supports_parallel=True
            )
            async def web_search(query: str, top_n: int = 5) -> SearchResponse:
                """Search the live web and return external evidence with source URLs."""
                return await self.search(query, top_n=top_n)

            items.append(web_search)
        if self.rag_provider is not None:

            @tool(
                name="rag_retrieve",
                namespace="knowledge",
                source="provider",
                supports_parallel=True,
            )
            async def rag_retrieve(query: str, top_n: int = 3) -> tuple[RAGDocument, ...]:
                """Retrieve external knowledge documents relevant to a query."""
                return await self.retrieve(query, top_n=top_n)

            items.append(rag_retrieve)
        if self.vision_provider is not None:

            @tool(
                name="vision_analyze",
                namespace="knowledge",
                source="provider",
                supports_parallel=True,
            )
            async def vision_analyze(image: str, prompt: str) -> VisionResult:
                """Analyze a local, data, or remote image with the configured vision provider."""
                return await self.vision(image, prompt)

            items.append(vision_analyze)
        return tuple(items)
