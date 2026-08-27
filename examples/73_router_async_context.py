"""Use an async predicate with immutable routing context."""

import asyncio
from collections.abc import Mapping
from typing import Any

from super_harness import Route, Router


async def enabled(value: str, context: Mapping[str, Any]) -> bool:
    await asyncio.sleep(0)
    return value == "deploy" and context.get("approved") is True


async def main() -> None:
    router = Router((Route("deploy", "release", enabled),), default="review")
    print(await router.aroute("deploy", context={"approved": True}))


asyncio.run(main())

