"""Discover a deferred tool without importing it until selected."""

import asyncio

from super_harness import ToolRegistry, tool


def load_weather():  # type information belongs at the plugin/application boundary
    @tool
    def weather(city: str) -> str:
        """Return deterministic demo weather."""
        return f"{city}: clear"

    return weather


registry = ToolRegistry()
registry.register_lazy("weather", "Look up weather", load_weather, source="demo")
print(registry.discover("weather"))
print(asyncio.run(registry.load("weather").invoke({"city": "Chengdu"})))
