"""Register and remove a tool while an application is running."""

import asyncio

from super_harness import ToolRegistry, tool


@tool
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"


registry = ToolRegistry()
registry.register(greet)
print(asyncio.run(registry.get("greet").invoke({"name": "Ada"})))
registry.unregister("greet")
