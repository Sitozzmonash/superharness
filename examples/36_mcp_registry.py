import asyncio

from super_harness import OfficialMCPRegistry


async def main() -> None:
    for server in await OfficialMCPRegistry().search("filesystem", limit=5):
        print(server)


asyncio.run(main())
