import asyncio

from super_harness import KnowledgeRouter, ZhipuWebSearchProvider


async def main() -> None:
    router = KnowledgeRouter(search=ZhipuWebSearchProvider())
    for fragment in await router.search_context("latest Python release", top_n=2):
        print(fragment.source, fragment.content)


asyncio.run(main())
