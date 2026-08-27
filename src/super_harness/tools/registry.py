"""Deterministic tool registry."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase

from super_harness.exceptions import ToolError
from super_harness.models import ToolDefinition

from .definition import Tool

LazyToolLoader = Callable[[], object]


@dataclass(frozen=True, slots=True)
class LazyTool:
    name: str
    description: str
    namespace: str | None = None
    source: str = "runtime"

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name


class ToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool] = (),
        *,
        allowed_names: Iterable[str] | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._disabled: set[str] = set()
        self._lazy: dict[str, tuple[LazyTool, LazyToolLoader]] = {}
        self._lock = threading.RLock()
        self._allowed_names = tuple(allowed_names) if allowed_names is not None else None
        for item in tools:
            self.register(item)

    def _require_allowed(self, name: str) -> None:
        if self._allowed_names is not None and not any(
            fnmatchcase(name, pattern) for pattern in self._allowed_names
        ):
            raise ToolError(f"tool {name!r} is outside the registry scope")

    def register(self, item: Tool) -> None:
        name = item.qualified_name
        self._require_allowed(name)
        with self._lock:
            if name in self._tools or name in self._lazy:
                raise ToolError(f"tool {name!r} is already registered")
            self._tools[name] = item

    def register_lazy(
        self,
        name: str,
        description: str,
        loader: LazyToolLoader,
        *,
        namespace: str | None = None,
        source: str = "runtime",
    ) -> LazyTool:
        metadata = LazyTool(name.strip(), description.strip(), namespace, source)
        qualified = metadata.qualified_name
        self._require_allowed(qualified)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", qualified):
            raise ToolError("lazy tool name is invalid")
        if not metadata.description or not callable(loader):
            raise ToolError("lazy tool description and loader are required")
        with self._lock:
            if qualified in self._tools or qualified in self._lazy:
                raise ToolError(f"tool {qualified!r} is already registered")
            self._lazy[qualified] = (metadata, loader)
        return metadata

    def load(self, name: str) -> Tool:
        with self._lock:
            if name in self._tools:
                return self.get(name)
            try:
                metadata, loader = self._lazy[name]
            except KeyError as exc:
                raise ToolError(f"unknown tool {name!r}") from exc
            try:
                loaded: object = loader()
            except Exception as exc:
                raise ToolError(
                    f"lazy tool {name!r} failed to load",
                    details={"tool": name, "source": metadata.source},
                ) from exc
            if not isinstance(loaded, Tool) or loaded.qualified_name != name:
                raise ToolError(f"lazy tool loader returned a mismatched tool for {name!r}")
            item = loaded
            self._lazy.pop(name)
            self._tools[name] = item
            return item

    def unregister(self, name: str) -> Tool:
        with self._lock:
            if name in self._lazy:
                raise ToolError("use unregister_lazy for an unloaded lazy tool")
            try:
                item = self._tools.pop(name)
            except KeyError as exc:
                raise ToolError(f"unknown tool {name!r}") from exc
            self._disabled.discard(name)
            return item

    def unregister_lazy(self, name: str) -> LazyTool:
        with self._lock:
            try:
                metadata, _ = self._lazy.pop(name)
            except KeyError as exc:
                raise ToolError(f"unknown lazy tool {name!r}") from exc
        return metadata

    def get(self, name: str) -> Tool:
        with self._lock:
            if name in self._disabled:
                raise ToolError(f"tool {name!r} is disabled")
            try:
                return self._tools[name]
            except KeyError as exc:
                raise ToolError(f"unknown tool {name!r}") from exc

    def enable(self, name: str) -> None:
        with self._lock:
            if name not in self._tools:
                raise ToolError(f"unknown tool {name!r}")
            self._disabled.discard(name)

    def disable(self, name: str) -> None:
        with self._lock:
            if name not in self._tools:
                raise ToolError(f"unknown tool {name!r}")
            self._disabled.add(name)

    def list(self, *, include_disabled: bool = False) -> tuple[Tool, ...]:
        with self._lock:
            return tuple(
                item
                for name, item in self._tools.items()
                if include_disabled or name not in self._disabled
            )

    def search(self, query: str, *, load_deferred: bool = False) -> tuple[Tool, ...]:
        needle = query.casefold().strip()
        found = tuple(
            item
            for item in self.list()
            if needle in item.qualified_name.casefold() or needle in item.description.casefold()
        )
        if not load_deferred:
            return found
        with self._lock:
            lazy_names = tuple(
                name
                for name, (item, _) in self._lazy.items()
                if needle in name.casefold() or needle in item.description.casefold()
            )
        return found + tuple(self.load(name) for name in lazy_names)

    def deferred(self) -> tuple[LazyTool, ...]:
        with self._lock:
            return tuple(item for item, _ in self._lazy.values())

    def discover(self, query: str = "") -> tuple[tuple[str, str, str, bool], ...]:
        needle = query.casefold().strip()
        loaded = (
            (item.qualified_name, item.description, item.metadata.source, False)
            for item in self.list()
        )
        deferred = (
            (item.qualified_name, item.description, item.source, True) for item in self.deferred()
        )
        return tuple(
            item
            for item in (*loaded, *deferred)
            if not needle or needle in item[0].casefold() or needle in item[1].casefold()
        )

    def definitions(self, *, include_deferred: bool = False) -> tuple[ToolDefinition, ...]:
        return tuple(
            item.provider_definition()
            for item in self.list()
            if include_deferred or not item.metadata.deferred
        )
