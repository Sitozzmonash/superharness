import asyncio

from super_harness import ZhipuVisionProvider


async def main() -> None:
    result = await ZhipuVisionProvider().analyze(
        "https://example.com/image.png", "List visible objects"
    )
    print(result.text)


asyncio.run(main())
