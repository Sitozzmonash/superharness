import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("math", MCPTransport.STDIO, command="python", args=("server.py",))
    async with MCPClient(config) as client:
        print(await client.call_tool("add", {"left": 20, "right": 22}))


asyncio.run(main())
