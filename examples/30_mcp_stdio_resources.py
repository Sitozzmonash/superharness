import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("notes", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print(await client.list_resources())
        print(await client.read_resource("note://release"))


asyncio.run(main())
