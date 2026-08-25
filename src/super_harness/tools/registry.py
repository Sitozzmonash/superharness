"""Deterministic tool registry."""

from __future__ import annotations

from collections.abc import Iterable

from super_harness.exceptions import ToolError
from super_harness.models import ToolDefinition

from .definition import Tool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()
        for item in tools:
            self.register(item)

    def register(self, item: Tool) -> None:
        name = item.qualified_name
        if name in self._tools:
            raise ToolError(f"tool {name!r} is already registered")
        self._tools[name] = item

    def unregister(self, name: str) -> Tool:
        try:
            item = self._tools.pop(name)
        except KeyError as exc:
            raise ToolError(f"unknown tool {name!r}") from exc
        self._disabled.discard(name)
        return item

    def get(self, name: str) -> Tool:
        if name in self._disabled:
            raise ToolError(f"tool {name!r} is disabled")
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"unknown tool {name!r}") from exc

    def enable(self, name: str) -> None:
        if name not in self._tools:
            raise ToolError(f"unknown tool {name!r}")
        self._disabled.discard(name)

    def disable(self, name: str) -> None:
        if name not in self._tools:
            raise ToolError(f"unknown tool {name!r}")
        self._disabled.add(name)

    def list(self, *, include_disabled: bool = False) -> tuple[Tool, ...]:
        return tuple(
            item
            for name, item in self._tools.items()
            if include_disabled or name not in self._disabled
        )

    def search(self, query: str) -> tuple[Tool, ...]:
        needle = query.casefold().strip()
        return tuple(
            item
            for item in self.list()
            if needle in item.qualified_name.casefold() or needle in item.description.casefold()
        )

    def definitions(self, *, include_deferred: bool = False) -> tuple[ToolDefinition, ...]:
        return tuple(
            item.provider_definition()
            for item in self.list()
            if include_deferred or not item.metadata.deferred
        )
