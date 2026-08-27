"""Load only deferred tools that match a namespace search."""

import asyncio

from super_harness import ToolRegistry, tool


@tool(namespace="ops")
def status(service: str) -> str:
    """Return a local service status."""
    return f"{service}=ready"


registry = ToolRegistry()
registry.register_lazy("status", "Service status", lambda: status, namespace="ops")
matched = registry.search("service", load_deferred=True)
print(asyncio.run(matched[0].invoke({"service": "api"})))
