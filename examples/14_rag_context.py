import asyncio

from super_harness import KnowledgeRouter
from super_harness.knowledge import HTTPRAGProvider


async def main() -> None:
    router = KnowledgeRouter(rag=HTTPRAGProvider())
    for fragment in await router.rag_context("authentication rules"):
        print(fragment.render().content)


asyncio.run(main())
