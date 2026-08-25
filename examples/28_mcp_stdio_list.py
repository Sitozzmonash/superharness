import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("demo", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print([tool.name for tool in await client.list_tools()])


asyncio.run(main())
