import asyncio

from super_harness import HTTPRAGProvider


async def main() -> None:
    for document in await HTTPRAGProvider().retrieve("release policy", top_n=3):
        print(document.source, document.score, document.text)


asyncio.run(main())
