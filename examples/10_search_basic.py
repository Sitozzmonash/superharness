import asyncio

from super_harness import ZhipuWebSearchProvider


async def main() -> None:
    response = await ZhipuWebSearchProvider().search("Python async context manager", top_n=3)
    for item in response.results:
        print(item.title, item.url)


asyncio.run(main())
