import asyncio
from pathlib import Path

from super_harness import ZhipuVisionProvider


async def main() -> None:
    result = await ZhipuVisionProvider().analyze(Path("image.png"), "Describe this image")
    print(result.text)


asyncio.run(main())
