"""External-process MCP 2.x compatibility fixture."""

from __future__ import annotations

import asyncio
import sys

from mcp.server import MCPServer

mcp = MCPServer("super-harness-test", version="1.0.0")


@mcp.tool()
def add(left: int, right: int) -> int:
    """Add two integers."""

    return left + right


@mcp.tool()
async def slow(delay: float) -> str:
    """Wait for a duration."""

    await asyncio.sleep(delay)
    return "done"


@mcp.resource("note://release")
def release_note() -> str:
    """Return a release note."""

    return "release requires canary"


@mcp.prompt()
def summarize(topic: str) -> str:
    """Create a summary prompt."""

    return f"Summarize {topic}"


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if transport == "streamable-http":
        mcp.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=int(sys.argv[2]),
            stateless_http=True,
            json_response=True,
        )
    else:
        mcp.run(transport="stdio")
