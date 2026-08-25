"""Representative MCP 1.x server used for the 2025 protocol compatibility E2E."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("super-harness-2025-compat")


@mcp.tool()
def legacy_add(left: int, right: int) -> int:
    """Add through an MCP 1.x server."""

    return left + right


if __name__ == "__main__":
    mcp.run(transport="stdio")
