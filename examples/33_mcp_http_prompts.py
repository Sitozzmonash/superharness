import asyncio

from super_harness import MCPClient, MCPServerConfig, MCPTransport


async def main() -> None:
    config = MCPServerConfig("remote", MCPTransport.STREAMABLE_HTTP, url="http://127.0.0.1:8000/mcp")
    async with MCPClient(config) as client:
        print(await client.list_prompts())
        print(await client.get_prompt("summarize", {"topic": "MCP"}))


asyncio.run(main())
